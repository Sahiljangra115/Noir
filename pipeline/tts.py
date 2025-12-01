"""
pipeline/tts.py
────────────────
Text-to-speech using piper-tts (fully offline, ONNX).
Voice: en_US amy-medium (already downloaded at ~/piper-voices/amy/).

Audio is rendered to an in-memory WAV buffer then piped to `aplay`
(Linux ALSA).  The speak() call is non-blocking by default — a daemon
thread handles playback so the main loop is never stalled.

If you want the robot to finish speaking before moving, call:
    tts.speak("text", block=True)

Usage:
    tts = PiperTTS()
    tts.speak("I am now following the line.")

To also relay TTS audio to the phone over WebSocket:
    tts.set_wav_callback(lambda wav: socketio.emit("tts_audio", wav))
"""

import io
import logging
import subprocess
import threading
import wave
from pathlib import Path

log = logging.getLogger(__name__)

# ── Default voice paths (amy-medium) ─────────────────────────────────────────
_VOICES_DIR  = Path("/home/ladliju/piper-voices/amy")
_MODEL_PATH  = _VOICES_DIR / "en_US-amy-medium.onnx"
_CONFIG_PATH = _VOICES_DIR / "en_US-amy-medium.onnx.json"


class PiperTTS:
    def __init__(
        self,
        model_path:  str | Path = _MODEL_PATH,
        config_path: str | Path = _CONFIG_PATH,
        use_cuda:    bool       = False,
    ) -> None:
        self._model_path  = Path(model_path)
        self._config_path = Path(config_path)
        self._use_cuda    = use_cuda
        self._voice       = None
        self._speak_lock  = threading.Lock()
        self._wav_callback = None   # optional: fn(wav_bytes) called before aplay

    # ── Lazy load ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._voice is not None:
            return
        try:
            from piper import PiperVoice
        except ImportError:
            raise RuntimeError(
                "piper-tts not installed.\n"
                "  uv pip install piper-tts"
            )

        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Piper model not found: {self._model_path}\n"
                "Download from https://huggingface.co/rhasspy/piper-voices"
            )

        config = str(self._config_path) if self._config_path.exists() else None
        print(f"[TTS] Loading piper voice: {self._model_path.name}")
        self._voice = PiperVoice.load(
            str(self._model_path),
            config_path=config,
            use_cuda=self._use_cuda,
        )
        print("[TTS] Piper TTS ready.")

    # ── Public API ────────────────────────────────────────────────────────────

    def set_wav_callback(self, fn) -> None:
        """Register a callback fn(wav_bytes: bytes) called on every utterance.
        Used by WebServer to relay TTS audio to the Flutter app over SocketIO."""
        self._wav_callback = fn

    def speak(self, text: str, block: bool = False) -> None:
        """
        Synthesise `text` and play it.

        block=False (default): spawns a daemon thread, returns immediately.
        block=True:            waits for playback to finish.
        """
        if not text.strip():
            return

        if block:
            self._speak_sync(text)
        else:
            t = threading.Thread(
                target=self._speak_sync,
                args=(text,),
                daemon=True,
            )
            t.start()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _speak_sync(self, text: str) -> None:
        """Render speech and play via aplay (blocking)."""
        self._load()
        assert self._voice is not None

        if not self._speak_lock.acquire(blocking=False):
            log.debug("[TTS] Skipped (already speaking): %s", text[:40])
            return

        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                self._voice.synthesize_wav(text, wf)
            wav_bytes = buf.getvalue()

            if self._wav_callback is not None:
                # Phone connected → phone speaker only, skip laptop aplay
                try:
                    self._wav_callback(wav_bytes)
                except Exception as exc:
                    log.debug("[TTS] wav_callback error: %s", exc)
            else:
                # No phone → play on laptop speaker via aplay
                proc = subprocess.Popen(
                    ["aplay", "--quiet", "-"],
                    stdin=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                proc.communicate(input=wav_bytes)

        except FileNotFoundError:
            log.error("[TTS] 'aplay' not found. Install: sudo apt install alsa-utils")
        except Exception as exc:
            log.error("[TTS] Playback error: %s", exc)
        finally:
            self._speak_lock.release()
