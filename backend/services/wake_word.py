"""
pipeline/wake_word.py
──────────────────────
Wake-word detector backed by openWakeWord (Apache-2.0).

Replaces Porcupine. No vendor key required.

Default keyword maps:
    "jarvis" / "hey_jarvis"  → hey_jarvis_v0.1.onnx
    "alexa"                  → alexa_v0.1.onnx
    "hey_mycroft"            → hey_mycroft_v0.1.onnx

Usage:
    det = WakeWordDetector(keyword="jarvis", sensitivity=0.5)
    det.wait_for_wakeword()   # blocks until detected
    det.close()
"""

import logging

log = logging.getLogger(__name__)

_SAMPLE_RATE = 16_000
_FRAME_SAMPLES = 1280

_KEYWORD_TO_MODEL_FILE = {
    "jarvis": "hey_jarvis_v0.1",
    "hey_jarvis": "hey_jarvis_v0.1",
    "alexa": "alexa_v0.1",
    "hey_mycroft": "hey_mycroft_v0.1",
}


class WakeWordDetector:
    def __init__(
        self,
        keyword: str = "jarvis",
        sensitivity: float = 0.5,
        access_key: str | None = None,
    ) -> None:
        self.keyword = keyword.lower()
        self.sensitivity = float(sensitivity)
        self._model = None
        self._model_key = _KEYWORD_TO_MODEL_FILE.get(self.keyword, "hey_jarvis_v0.1")
        if access_key:
            log.debug("[WAKE] access_key arg ignored — openWakeWord requires no key")

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import openwakeword
            from openwakeword.model import Model
        except ImportError:
            raise RuntimeError(
                "openwakeword not installed.\n"
                "  uv pip install openwakeword"
            )

        all_paths = openwakeword.get_pretrained_model_paths()
        match = [p for p in all_paths if self._model_key in p]
        if not match:
            raise RuntimeError(
                f"[WAKE] model '{self._model_key}' not found in openwakeword resources.\n"
                f"  available: {all_paths}"
            )

        self._model = Model(wakeword_model_paths=match)
        log.info(
            "[WAKE] openWakeWord ready — model='%s' (sens=%.2f) frame=%d sr=%d",
            self._model_key, self.sensitivity, _FRAME_SAMPLES, _SAMPLE_RATE,
        )
        print(f"[WAKE] Say '{self.keyword.capitalize()}' to activate.")

    def wait_for_wakeword(self) -> None:
        """Block until wake word detected on default mic."""
        self._load()

        try:
            import sounddevice as sd
        except ImportError:
            raise RuntimeError(
                "sounddevice not installed.\n"
                "  uv pip install sounddevice\n"
                "  sudo apt install portaudio19-dev"
            )

        import numpy as np

        log.debug("[WAKE] Listening for '%s'…", self.keyword)

        recent_scores: list = []
        SMOOTH_WINDOW = 3
        with sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=_FRAME_SAMPLES,
        ) as stream:
            while True:
                pcm_chunk, _ = stream.read(_FRAME_SAMPLES)
                audio = np.asarray(pcm_chunk, dtype=np.int16).flatten()
                scores = self._model.predict(audio)
                score = float(scores.get(self._model_key, 0.0))
                recent_scores.append(score)
                if len(recent_scores) > SMOOTH_WINDOW:
                    recent_scores.pop(0)
                smooth = sum(recent_scores) / len(recent_scores)
                peak = max(recent_scores)
                if peak >= self.sensitivity or smooth >= self.sensitivity * 0.8:
                    log.info(
                        "[WAKE] '%s' detected (peak=%.2f smooth=%.2f thresh=%.2f)",
                        self.keyword, peak, smooth, self.sensitivity,
                    )
                    print(f"\n[WAKE] '{self.keyword.capitalize()}' detected — listening…")
                    return

    def wait_for_wakeword_from_queue(
        self,
        audio_queue,
        stop_event=None,
    ) -> bool:
        """Block until wake word detected on PCM16 chunks arriving via queue.

        Returns True on detection, False if stop_event is set first.
        Phone chunks are variable-size; buffer into 1280-sample frames.
        """
        self._load()

        import queue as _q
        import numpy as np

        log.debug("[WAKE] Listening (phone) for '%s'…", self.keyword)

        buf = np.zeros(0, dtype=np.int16)
        # 3-frame moving avg smooths borderline scores so easy speech triggers
        recent_scores: list = []
        SMOOTH_WINDOW = 3
        while True:
            if stop_event is not None and stop_event.is_set():
                return False
            try:
                raw = audio_queue.get(timeout=0.1)
            except _q.Empty:
                continue
            if not raw or len(raw) < 2:
                continue
            if len(raw) % 2:
                raw = raw[:-1]
            chunk = np.frombuffer(raw, dtype=np.int16)
            buf = np.concatenate([buf, chunk]) if buf.size else chunk

            while buf.size >= _FRAME_SAMPLES:
                frame = buf[:_FRAME_SAMPLES]
                buf = buf[_FRAME_SAMPLES:]
                scores = self._model.predict(frame)
                score = float(scores.get(self._model_key, 0.0))
                recent_scores.append(score)
                if len(recent_scores) > SMOOTH_WINDOW:
                    recent_scores.pop(0)
                smooth = sum(recent_scores) / len(recent_scores)
                peak = max(recent_scores)
                # Trigger on either instant peak or smoothed run — easier to wake
                if peak >= self.sensitivity or smooth >= self.sensitivity * 0.8:
                    log.info(
                        "[WAKE] '%s' detected (phone peak=%.2f smooth=%.2f thresh=%.2f)",
                        self.keyword, peak, smooth, self.sensitivity,
                    )
                    print(f"\n[WAKE] '{self.keyword.capitalize()}' detected (phone) — listening…")
                    return True

    def close(self) -> None:
        if self._model is not None:
            try:
                if hasattr(self._model, "reset"):
                    self._model.reset()
            except Exception:
                pass
            self._model = None
