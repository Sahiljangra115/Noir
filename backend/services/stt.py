"""
pipeline/stt.py
────────────────
Records from the microphone and transcribes using faster-whisper.

Two input sources are supported:
  listen()            — records from the laptop mic via sounddevice
  listen_from_queue() — reads PCM16 chunks from a queue (phone mic over WebSocket)

Recording strategy (both methods)
──────────────────────────────────
  1. Wait up to `no_speech_timeout` seconds for speech to start.
  2. Once speech is detected, record until `silence_timeout` seconds
     of continuous silence → stop early.
  3. Hard cap at `max_duration` seconds regardless.

Whisper's built-in Silero VAD is still enabled during transcription to
clean up any residual silence in the recorded buffer.
"""

import logging
import queue
import numpy as np

log = logging.getLogger(__name__)

_SAMPLE_RATE      = 16_000
_CHUNK            = 512
_ENERGY_THRESHOLD = 800    # slightly more sensitive
_SILENCE_TIMEOUT   = 0.2    # s - extra aggressive, fastest possible silence
_NO_SPEECH_TIMEOUT = 2.0    # s - much shorter wait for no speech


class WhisperSTT:
    def __init__(
        self,
        model_size:   str = "tiny",
        device:       str = "auto",
        compute_type: str = "auto",
        energy_threshold: int = _ENERGY_THRESHOLD,
    ) -> None:
        self.model_size   = model_size
        self.device       = device
        self.compute_type = compute_type
        self.energy_threshold = energy_threshold
        self._model       = None

    # ── Lazy load ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError(
                "faster-whisper not installed.\n"
                "  uv pip install faster-whisper"
            )

        device       = self.device
        compute_type = self.compute_type

        if device == "auto":
            try:
                import torch
                if torch.cuda.is_available():
                    device       = "cuda"
                    compute_type = "int8" if compute_type == "auto" else compute_type
                    log.info("[STT] CUDA available — using GPU")
                else:
                    raise RuntimeError("CUDA not available")
            except Exception:
                device       = "cpu"
                compute_type = "int8" if compute_type == "auto" else compute_type
                log.warning("[STT] CUDA unavailable — falling back to CPU (slower)")

        if compute_type == "auto":
            compute_type = "int8"

        print(f"[STT] Loading Whisper '{self.model_size}' on {device}…")
        self._model = WhisperModel(
            self.model_size,
            device=device,
            compute_type=compute_type,
            local_files_only=False, # Allow model download if needed
        )
        print("[STT] Whisper ready.")

    # ── Public API ────────────────────────────────────────────────────────────

    def listen(
        self,
        max_duration:      float = 12.0,   # shorter max
        silence_timeout:   float = _SILENCE_TIMEOUT,
        no_speech_timeout: float = _NO_SPEECH_TIMEOUT,
    ) -> str:
        """Record from the laptop mic until the user stops speaking."""
        self._load()

        try:
            import sounddevice as sd
        except ImportError:
            raise RuntimeError(
                "sounddevice not installed.\n"
                "  uv pip install sounddevice"
            )

        max_chunks         = int(max_duration      * _SAMPLE_RATE / _CHUNK)
        silence_chunks_max = int(silence_timeout   * _SAMPLE_RATE / _CHUNK)
        no_speech_max      = int(no_speech_timeout * _SAMPLE_RATE / _CHUNK)

        frames:            list  = []
        speech_detected:   bool  = False
        silence_chunks:    int   = 0
        no_speech_chunks:  int   = 0

        # Keep a small pre-roll buffer to avoid cutting off the start of the sentence
        pre_roll:          list  = []
        PRE_ROLL_SIZE      = 5   # approx 160ms

        print("[STT] Listening…", end=" ", flush=True)

        with sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=_CHUNK,
        ) as stream:
            for _ in range(max_chunks):
                chunk, _ = stream.read(_CHUNK)
                rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

                if not speech_detected:
                    pre_roll.append(chunk.copy())
                    if len(pre_roll) > PRE_ROLL_SIZE:
                        pre_roll.pop(0)

                    if rms > self.energy_threshold:
                        speech_detected = True
                        frames.extend(pre_roll)
                        print("◉", end=" ", flush=True)
                    else:
                        no_speech_chunks += 1
                        if no_speech_chunks >= no_speech_max:
                            print("[no speech detected]")
                            return ""
                else:
                    frames.append(chunk.copy())
                    if rms < self.energy_threshold:
                        silence_chunks += 1
                        if silence_chunks >= silence_chunks_max:
                            print("[done]")
                            break
                    else:
                        silence_chunks = 0

        if not speech_detected:
            return ""

        return self._transcribe(frames)

    def listen_from_queue(
        self,
        audio_queue: queue.Queue,
        max_duration:      float = 12.0,
        silence_timeout:   float = _SILENCE_TIMEOUT,
        no_speech_timeout: float = _NO_SPEECH_TIMEOUT,
    ) -> str:
        """
        Transcribe audio arriving as PCM16 bytes via a Queue.

        The Flutter app streams PCM16 LE (16 kHz, mono) binary chunks
        continuously. This reads them with the same energy-based VAD as listen().

        Each queue item must be a bytes object (PCM16 LE, 512 samples = 1024 bytes).
        Returns transcribed text, or "" on timeout / no speech.
        """
        self._load()

        max_chunks         = int(max_duration      * _SAMPLE_RATE / _CHUNK)
        silence_chunks_max = int(silence_timeout   * _SAMPLE_RATE / _CHUNK)
        no_speech_max      = int(no_speech_timeout * _SAMPLE_RATE / _CHUNK)

        frames:           list = []
        speech_detected:  bool = False
        silence_chunks:   int  = 0
        no_speech_chunks: int  = 0

        # Pre-roll buffer for phone queue
        pre_roll:         list = []
        PRE_ROLL_SIZE     = 5

        print("[STT] Listening (phone)…", end=" ", flush=True)

        for _ in range(max_chunks):
            try:
                raw: bytes = audio_queue.get(timeout=0.1)
            except queue.Empty:
                if speech_detected:
                    silence_chunks += 1
                    if silence_chunks >= silence_chunks_max:
                        print("[done]")
                        break
                else:
                    no_speech_chunks += 1
                    if no_speech_chunks >= no_speech_max:
                        print("[no speech detected]")
                        return ""
                continue

            chunk = np.frombuffer(raw, dtype=np.int16).reshape(-1, 1)
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

            if not speech_detected:
                pre_roll.append(chunk.copy())
                if len(pre_roll) > PRE_ROLL_SIZE:
                    pre_roll.pop(0)

                if rms > self.energy_threshold:
                    speech_detected = True
                    frames.extend(pre_roll)
                    print("◉", end=" ", flush=True)
                else:
                    no_speech_chunks += 1
                    if no_speech_chunks >= no_speech_max:
                        print("[no speech detected]")
                        return ""
            else:
                frames.append(chunk.copy())
                if rms < self.energy_threshold:
                    silence_chunks += 1
                    if silence_chunks >= silence_chunks_max:
                        print("[done]")
                        break
                else:
                    silence_chunks = 0

        if not speech_detected or not frames:
            return ""

        return self._transcribe(frames)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _transcribe(self, frames: list) -> str:
        audio = (
            np.concatenate(frames, axis=0)
            .flatten()
            .astype(np.float32) / 32_768.0
        )

        if self._model is None:
            log.error("[STT] Model failed to load")
            return ""

        segments, _ = self._model.transcribe(
            audio,
            language="en",
            beam_size=3,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300),
        )

        text = " ".join(seg.text.strip() for seg in segments).strip()
        print(f"→ '{text}'")
        log.info("[STT] Transcribed: %s", text)
        return text
