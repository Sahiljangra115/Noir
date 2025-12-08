"""
vision_processor.py – VLA (Vision-Language-Action) Layer
──────────────────────────────────────────────────────────
Sends a JPEG-encoded frame to a locally-running Ollama instance
(model: moondream or llava) and parses the reply into one of four
high-level navigation intents:

    FOLLOW  – a person is visible and reachable
    SEARCH  – no person in frame, rotate to find one
    STOP    – obstacle too close / unknown situation
    AVOID   – danger / blocked path

The class is intentionally thin so main.py stays easy to read.
Heavy CV work (YOLO, line following) lives in tracker.py.

Usage:
    vla = VLAProcessor()
    intent = vla.get_intent(frame)   # returns one of FOLLOW/SEARCH/STOP/AVOID
"""

import base64
import hashlib
import logging
import time
from typing import Optional

import cv2
import numpy as np
import requests
log = logging.getLogger(__name__)

# ── Ollama defaults ────────────────────────────────────────────────────────────
_OLLAMA_URL   = "http://localhost:11434/api/generate"
_DEFAULT_MODEL = "moondream"       # swap to "llava" if moondream isn't pulled
_TIMEOUT_S    = 6                  # seconds – keep short; GPU is fast locally
_JPEG_QUALITY = 65                 # lower quality = smaller payload = faster

# Performance optimization settings
_CACHE_DURATION_S = 1.5            # Cache VLA responses for similar frames
_FRAME_RESIZE_MAX = 640            # Resize large frames for faster processing

# The reply must be exactly one of these tokens (case-insensitive match)
_VALID_INTENTS = frozenset({"FOLLOW", "SEARCH", "STOP", "AVOID"})

_PROMPT = (
    "You are the navigation brain of a wheeled robot. "
    "Look at this image and reply with EXACTLY one word from this list:\n"
    "  FOLLOW – a person is clearly visible and you should follow them.\n"
    "  SEARCH – no person is visible; the robot should rotate to find one.\n"
    "  STOP   – an obstacle is dangerously close or the path is completely blocked.\n"
    "  AVOID  – there is a hazard (stairs, edge, wall very close).\n"
    "Reply with ONLY that single word. No punctuation. No explanation."
)


class VLAProcessor:
    """
    Wraps the Ollama REST API for vision-language navigation decisions.
    Includes caching and frame optimization for better performance.

    The get_intent() call is synchronous (it blocks until the model replies).
    main.py calls it on a timer (e.g. every 2 s) so the main CV loop is not
    blocked on every frame.
    """

    def __init__(
        self,
        ollama_url: str = _OLLAMA_URL,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        # Input validation
        if not isinstance(ollama_url, str) or not ollama_url:
            raise ValueError(f"Invalid ollama_url: {ollama_url!r}")
        if not isinstance(model, str) or not model:
            raise ValueError(f"Invalid model: {model!r}")

        self.url   = ollama_url
        self.model = model
        self._last_call: float = 0.0

        # Performance optimization: response caching
        self._cache: dict[str, tuple[str, float]] = {}  # frame_hash -> (intent, timestamp)
        self._session = requests.Session()  # Reuse connections

        # Connection optimization
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=2,
            max_retries=0  # Fast fail for real-time operation
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        # Circuit breaker pattern for reliability
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._circuit_open = False
        self._max_failures = 3
        self._circuit_timeout = 30.0  # 30 seconds

        log.info("[VLA] Processor ready – model=%s  url=%s", model, ollama_url)
        print(f"[VLA] Using model '{model}' via Ollama at {ollama_url}")

    def _compute_frame_hash(self, frame: np.ndarray) -> str:
        """Compute hash of frame for caching purposes."""
        # Use a smaller sample for faster hashing
        h, w = frame.shape[:2]
        sample = frame[::h//8, ::w//8]  # Sample every 8th pixel
        return hashlib.md5(sample.tobytes()).hexdigest()[:16]  # Use first 16 chars

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_intent(self, frame: np.ndarray) -> str:
        """
        Encode *frame*, query Ollama, return a validated intent string.
        Uses caching, circuit breaker pattern, and frame optimization for reliability.
        Falls back to 'STOP' on any error so the bot never drives blindly.
        """
        # Input validation
        if frame is None or frame.size == 0:
            log.warning("[VLA] Invalid frame provided")
            return "STOP"

        if not isinstance(frame, np.ndarray) or len(frame.shape) != 3:
            log.warning("[VLA] Frame must be 3D numpy array, got: %s", type(frame))
            return "STOP"

        # Circuit breaker check
        current_time = time.monotonic()
        if self._circuit_open:
            if current_time - self._last_failure_time > self._circuit_timeout:
                log.info("[VLA] Circuit breaker reset - attempting reconnection")
                self._circuit_open = False
                self._failure_count = 0
            else:
                log.debug("[VLA] Circuit breaker open - returning STOP")
                return "STOP"

        # Check cache first
        try:
            frame_hash = self._compute_frame_hash(frame)
        except Exception as exc:
            log.warning("[VLA] Frame hash computation failed: %s", exc)
            return "STOP"

        if frame_hash in self._cache:
            cached_intent, timestamp = self._cache[frame_hash]
            if current_time - timestamp < _CACHE_DURATION_S:
                log.debug("[VLA] Cache hit for frame hash %s -> %s", frame_hash[:8], cached_intent)
                return cached_intent

        # Clean expired cache entries (keep cache size manageable)
        try:
            self._cache = {
                h: (intent, ts) for h, (intent, ts) in self._cache.items()
                if current_time - ts < _CACHE_DURATION_S * 2
            }
        except Exception as exc:
            log.warning("[VLA] Cache cleanup failed: %s", exc)
            self._cache.clear()  # Clear corrupt cache

        # Optimize frame size for faster processing
        try:
            optimized_frame = self._optimize_frame(frame)
            img_b64 = self._encode_frame(optimized_frame)
            if img_b64 is None:
                self._record_failure("Frame encoding failed")
                return "STOP"
        except Exception as exc:
            self._record_failure(f"Frame processing failed: {exc}")
            return "STOP"

        payload = {
            "model":  self.model,
            "prompt": _PROMPT,
            "images": [img_b64],
            "stream": False,
        }

        t0 = time.monotonic()
        try:
            resp = self._session.post(self.url, json=payload, timeout=_TIMEOUT_S)
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip().upper()

            # Reset failure count on success
            self._failure_count = 0

        except requests.exceptions.Timeout:
            self._record_failure(f"Request timed out (>{_TIMEOUT_S}s)")
            return "STOP"
        except requests.exceptions.ConnectionError as exc:
            self._record_failure(f"Connection error: {exc}")
            return "STOP"
        except Exception as exc:
            self._record_failure(f"Request failed: {exc}")
            return "STOP"

        elapsed = time.monotonic() - t0

        # Parse and validate response
        try:
            token = raw.split()[0] if raw.split() else "STOP"
            intent = token if token in _VALID_INTENTS else "STOP"

            if intent == "STOP" and token != "STOP":
                log.warning("[VLA] Invalid response token '%s', defaulting to STOP", token)

        except Exception as exc:
            log.warning("[VLA] Response parsing failed: %s", exc)
            intent = "STOP"

        # Cache the result
        try:
            self._cache[frame_hash] = (intent, current_time)
        except Exception as exc:
            log.warning("[VLA] Failed to cache result: %s", exc)

        log.debug("[VLA] raw=%r  intent=%s  (%.2fs)", raw, intent, elapsed)
        print(f"[VLA] intent={intent}  raw={raw!r}  ({elapsed:.2f}s)")
        return intent

    def _record_failure(self, error_msg: str) -> None:
        """Record a failure for circuit breaker pattern."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        log.warning("[VLA] %s (failure %d/%d)", error_msg, self._failure_count, self._max_failures)

        if self._failure_count >= self._max_failures:
            self._circuit_open = True
            log.warning("[VLA] Circuit breaker opened - too many failures")

    def is_ollama_running(self) -> bool:
        """Quick health-check. Returns True if Ollama is reachable."""
        try:
            r = requests.get("http://localhost:11434/", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    # ── Private helpers ────────────────────────────────────────────────────────

    def _optimize_frame(self, frame: np.ndarray) -> np.ndarray:
        """Resize frame if needed for faster processing."""
        h, w = frame.shape[:2]
        if max(h, w) > _FRAME_RESIZE_MAX:
            scale = _FRAME_RESIZE_MAX / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        return frame

    @staticmethod
    def _encode_frame(frame: np.ndarray) -> Optional[str]:
        """JPEG-encode a BGR frame and return a base-64 string."""
        try:
            ok, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY]
            )
            if not ok:
                return None
            return base64.b64encode(buf).decode("utf-8")
        except Exception as exc:
            log.error("[VLA] Frame encode failed: %s", exc)
            return None
