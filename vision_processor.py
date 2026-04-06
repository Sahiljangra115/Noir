"""
vision_processor.py – Gemma 4 VLA (Vision-Language-Action) Layer
───────────────────────────────────────────────────────────────
Sends a JPEG-encoded frame to a locally-running Ollama instance
(model: gemma4-e2b-nothink:latest) and parses the reply into a 
unified JSON object containing both speech and actions.

The model only receives a frame when a "significant change" is 
detected via OpenCV, saving compute and preventing redundant calls.
"""

import base64
import hashlib
import logging
import time
import json
import re
from typing import Optional, Dict, Any

import cv2
import numpy as np
import requests
log = logging.getLogger(__name__)

# ── Ollama defaults ────────────────────────────────────────────────────────────
_OLLAMA_URL    = "http://localhost:11434/api/generate"
_DEFAULT_MODEL = "gemma4-e2b-nothink:latest"
_TIMEOUT_S     = 20                 # Vision LLMs need more time than text
_JPEG_QUALITY  = 65
_FRAME_RESIZE_MAX = 640

# ── Thresholds ────────────────────────────────────────────────────────────────
_DIFF_THRESHOLD = 15.0              # MSE threshold for "significant change"

_PROMPT = """\
You are the navigation and perception brain of JARVIS, a wheeled robot.
Analyze this image and describe what you see, specifically focusing on your progress if you have a goal.

Respond with ONLY a raw JSON object — no markdown, no preamble.
Respond with ONLY a JSON object in this format:
{
    "speech": "Short description of what you see or your progress.",
    "actions": [{"type": "move", "cmd": "F", "duration": 2.0}]
}

Available movement commands: F (Forward), B (Backward), L (Left), R (Right), S (Stop).
Keep durations short (1.0 to 3.0 seconds).
"""

class GemmaVLAProcessor:
    """
    Event-driven VLA processor using Gemma 4.
    Only triggers inference when visual changes are detected.
    """

    def __init__(
        self,
        ollama_url: str = _OLLAMA_URL,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        self.url   = ollama_url
        self.model = model
        self._last_analyzed_frame: Optional[np.ndarray] = None
        self._session = requests.Session()
        
        # Connection optimization
        adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=2)
        self._session.mount("http://", adapter)
        
        log.info("[VLA] Gemma VLA ready – model=%s", model)

    def has_significant_change(self, frame: np.ndarray) -> bool:
        """
        Detects if the frame has changed enough to warrant a new LLM analysis.
        Uses a fast MSE comparison on downsampled grayscale images.
        """
        if self._last_analyzed_frame is None:
            return True
            
        try:
            # 1. Prepare small grayscale versions (64x64 is plenty for change detection)
            curr_small = cv2.cvtColor(cv2.resize(frame, (64, 64)), cv2.COLOR_BGR2GRAY)
            last_small = cv2.cvtColor(cv2.resize(self._last_analyzed_frame, (64, 64)), cv2.COLOR_BGR2GRAY)
            
            # 2. Calculate Mean Squared Error (MSE)
            diff = cv2.absdiff(curr_small, last_small)
            mse = np.mean(diff)
            
            # log.debug("[VLA] Frame diff MSE: %.2f", mse)
            return mse > _DIFF_THRESHOLD
            
        except Exception as exc:
            log.warning("[VLA] Change detection failed: %s", exc)
            return True

    def get_response(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Sends frame to Gemma 4 and returns parsed JSON response.
        """
        self._last_analyzed_frame = frame.copy()
        
        try:
            optimized_frame = self._optimize_frame(frame)
            img_b64 = self._encode_frame(optimized_frame)
            if not img_b64:
                return self._fallback("I failed to process the image.")
        except Exception as exc:
            log.error("[VLA] Image preparation failed: %s", exc)
            return self._fallback("Internal image error.")

        payload = {
            "model":  self.model,
            "prompt": _PROMPT,
            "images": [img_b64],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2}
        }

        t0 = time.monotonic()
        try:
            resp = self._session.post(self.url, json=payload, timeout=_TIMEOUT_S)
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()
        except Exception as exc:
            log.error("[VLA] Ollama request failed: %s", exc)
            return self._fallback("I couldn't reach my vision model.")

        elapsed = time.monotonic() - t0
        log.debug("[VLA] Response in %.2fs: %s", elapsed, raw[:100])
        
        return self._parse_json(raw)

    def _parse_json(self, raw: str) -> Dict[str, Any]:
        raw = re.sub(r"```(?:json)?", "", raw).strip()
        if not (raw.startswith("{") and raw.endswith("}")):
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match: raw = match.group()

        try:
            return json.loads(raw)
        except Exception:
            log.warning("[VLA] Failed to parse JSON: %s", raw)
            return self._fallback("I had trouble describing what I saw.")

    def _fallback(self, speech: str) -> Dict[str, Any]:
        return {"speech": speech, "actions": []}

    def _optimize_frame(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if max(h, w) > _FRAME_RESIZE_MAX:
            scale = _FRAME_RESIZE_MAX / max(h, w)
            return cv2.resize(frame, (int(w * scale), int(h * scale)))
        return frame

    @staticmethod
    def _encode_frame(frame: np.ndarray) -> Optional[str]:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
        return base64.b64encode(buf).decode("utf-8") if ok else None

# ── Legacy VLA (Commented Out) ────────────────────────────────────────────────
"""
_VALID_INTENTS = frozenset({"FOLLOW", "SEARCH", "STOP", "AVOID"})

class VLAProcessor:
    def __init__(self, ollama_url: str = _OLLAMA_URL, model: str = "moondream") -> None:
        self.url = ollama_url
        self.model = model
        self._session = requests.Session()

    def get_intent(self, frame: np.ndarray) -> str:
        # ... logic for single-word navigation ...
        return "STOP"
"""

