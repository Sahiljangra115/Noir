"""
pipeline/wake_word.py
──────────────────────
Continuously listens on the microphone and blocks until the
configured wake word is detected.

Uses Porcupine by Picovoice — extremely accurate, runs on CPU,
< 1% CPU load.  GPU stays fully free for Whisper and YOLO.

Built-in keywords available on Linux (no .ppn file needed):
    "jarvis"        ← default (say "Jarvis")
    "alexa"
    "bumblebee"
    "computer"
    "grasshopper"
    "picovoice"
    "porcupine"
    "terminator"

Requires a FREE Picovoice access key:
    1. Sign up at https://console.picovoice.ai  (30 seconds)
    2. Copy your Access Key
    3. Set environment variable:
           export PORCUPINE_ACCESS_KEY="your_key_here"
       Or add it to a .env file in the project root.

Usage:
    det = WakeWordDetector(keyword="jarvis")
    det.wait_for_wakeword()     # blocks until "Jarvis" is spoken
"""

import logging
import os

log = logging.getLogger(__name__)

# Porcupine audio requirements
_SAMPLE_RATE = 16_000   # Hz  (fixed by Porcupine)
# frame_length is obtained from the live porcupine instance (always 512)


class WakeWordDetector:
    def __init__(
        self,
        keyword:    str = "jarvis",
        access_key: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        keyword     : built-in keyword name (see module docstring for full list)
        access_key  : Picovoice access key.  If None, reads from the
                      PORCUPINE_ACCESS_KEY environment variable.
        """
        self.keyword    = keyword.lower()
        self.access_key = access_key or os.environ.get("PORCUPINE_ACCESS_KEY", "")
        self._handle    = None    # pvporcupine instance, lazy-loaded

    # ── Lazy load ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._handle is not None:
            return

        if not self.access_key:
            raise RuntimeError(
                "\n[WAKE] Porcupine access key not set!\n"
                "  1. Get a free key at https://console.picovoice.ai\n"
                "  2. export PORCUPINE_ACCESS_KEY='your_key_here'\n"
            )

        try:
            import pvporcupine
        except ImportError:
            raise RuntimeError(
                "pvporcupine not installed.\n"
                "  uv pip install pvporcupine"
            )

        # Validate keyword
        available = list(pvporcupine.KEYWORDS)
        if self.keyword not in available:
            raise ValueError(
                f"Unknown keyword '{self.keyword}'.\n"
                f"Available: {sorted(available)}"
            )

        self._handle = pvporcupine.create(
            access_key=self.access_key,
            keywords=[self.keyword],
        )
        log.info(
            "[WAKE] Porcupine ready — keyword='%s'  frame=%d  sr=%d",
            self.keyword, self._handle.frame_length, self._handle.sample_rate,
        )
        print(f"[WAKE] Say '{self.keyword.capitalize()}' to activate.")

    # ── Public API ────────────────────────────────────────────────────────────

    def wait_for_wakeword(self) -> None:
        """
        Block the calling thread until the wake word is spoken.
        Runs entirely on CPU — GPU stays free for Whisper + YOLO.
        """
        self._load()

        try:
            import sounddevice as sd
        except ImportError:
            raise RuntimeError(
                "sounddevice not installed.\n"
                "  uv pip install sounddevice\n"
                "  sudo apt install portaudio19-dev"
            )

        frame_len = self._handle.frame_length   # 512 samples @ 16 kHz

        log.debug("[WAKE] Listening for '%s'…", self.keyword)

        with sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=frame_len,
        ) as stream:
            while True:
                pcm_chunk, _ = stream.read(frame_len)
                pcm_flat = pcm_chunk.flatten().tolist()

                result = self._handle.process(pcm_flat)
                # result >= 0 → keyword index detected; -1 → nothing
                if result >= 0:
                    log.info("[WAKE] '%s' detected", self.keyword)
                    print(f"\n[WAKE] '{self.keyword.capitalize()}' detected — listening…")
                    return

    def close(self) -> None:
        """Release Porcupine resources. Call on shutdown."""
        if self._handle is not None:
            self._handle.delete()
            self._handle = None
