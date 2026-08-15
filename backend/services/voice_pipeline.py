"""
pipeline/voice_pipeline.py
───────────────────────────
Top-level orchestrator for the STT → LLM → TTS + Actions pipeline.

Flow on each activation
────────────────────────
1. WakeWordDetector blocks until the wake word is heard (openWakeWord) OR the
   force_listen event is set (Flutter arc reactor tap / laptop spacebar)
2. WhisperSTT records — from the phone queue if connected, else the laptop mic
3. CUSTOM_RESPONSES checked first — instant reply for known phrases
4. "bye" ends the exchange
5. Emergency keyword check → immediate STOP if detected
6. Visual context (YOLO info) injected into the LLM prompt
7. LLMParser sends to Gemma 4 → receives {speech, actions}
8. PiperTTS speaks the reply (non-blocking, also sent to phone via callback)
9. CommandQueue receives the action list
10. Loop back to step 1

All of this runs in a single daemon thread so the CV loop in
main.py is never blocked.

Usage (from main.py):
    state    = RobotState()
    pipeline = VoicePipeline(comms=robot_comms, state=state)
    pipeline.start()
"""

import logging
import queue
import re
import time
import threading
from uuid import uuid4

from .command_queue  import CommandQueue
from .llm_parser     import EMERGENCY_KEYWORDS, LLMParser
from .logging_setup  import set_corr_id
from .stt            import WhisperSTT
from .tts            import PiperTTS
from .wake_word      import WakeWordDetector
from backend.config  import config

log = logging.getLogger(__name__)

# Pre-compile regex patterns for efficiency
CUSTOM_RESPONSES_COMPILED = [
    (re.compile(r"\b(who made|who built|who created|who programmed) you\b"),
        "I was built by my creator as a final year engineering project. "
        "They designed me to be an autonomous robot assistant."),

    (re.compile(r"\bwhat (is your name|are you called|do (i|we) call you)\b"),
        "I'm jarvis. Short for Just A Rather Very Intelligent System."),

    (re.compile(r"\bwhat (can you do|are your capabilities|are you capable of)\b"),
        "I can follow lines, track people, navigate autonomously using my camera, "
        "respond to voice commands, and hold a conversation. "
        "Pretty good for a final year project, right?"),

    (re.compile(r"\b(are you|jarvis are you) (alive|conscious|sentient)\b"),
        "I'm not conscious, no. I'm an AI running on a laptop. "
        "But I do my best to be useful."),

    (re.compile(r"^(hello|hi|hey)( there| jarvis)?[.!?]?$"),
        "Hey, what do you need?"),

    (re.compile(r"\bthank(s| you)\b"),
        "Anytime."),

    (re.compile(r"\bjoke\b"),
        "Why do robots never panic? Because they have nerves of steel. "
        "And absolutely no nervous system."),
]


class VoicePipeline:
    def __init__(
        self,
        comms,
        state,
        wakeword:      str | None = None,
        wake_sensitivity: float | None = None,
        whisper_model: str | None = None,
        llm_model:     str | None = None,
        stt_threshold: int = 850,
        enable_wake_word: bool = True,
    ) -> None:
        # Defaults come from config so JARVIS_WHISPER_MODEL / _WAKE_KEYWORD /
        # _OLLAMA_MODEL actually take effect. They used to be literals here,
        # which pinned Whisper to "tiny" no matter what the env said.
        wakeword = wakeword or config.WAKE_KEYWORD
        wake_sensitivity = (
            config.WAKE_SENSITIVITY if wake_sensitivity is None else wake_sensitivity
        )
        whisper_model = whisper_model or config.WHISPER_MODEL
        llm_model = llm_model or config.OLLAMA_MODEL

        self._state  = state
        self._thread = None

        print("[PIPELINE] Initialising components…")

        self._enable_wake_word = enable_wake_word
        self.wakeword  = WakeWordDetector(keyword=wakeword, sensitivity=wake_sensitivity)
        self.stt       = WhisperSTT(
            model_size=whisper_model,
            device=config.WHISPER_DEVICE,
            energy_threshold=stt_threshold,
        )
        self.tts       = PiperTTS()
        self.llm       = LLMParser(model=llm_model)
        self.cmd_queue = CommandQueue(comms=comms, robot_state=state)

        # Give TTS access to robot state for camera-based audio routing
        self.tts.set_robot_state(state)

        # Eager warm-up: load Whisper + Piper in parallel so first request
        # does not pay model-init cost (CUDA context + ONNX). 2-8s saved.
        warm_stt = threading.Thread(target=self.stt._load, name="stt-warmup", daemon=True)
        warm_tts = threading.Thread(target=self.tts._load, name="tts-warmup", daemon=True)
        warm_stt.start()
        warm_tts.start()

        print(
            f"[PIPELINE] Ready — wake word: '{wakeword if enable_wake_word else 'DISABLED'}' | "
            f"Whisper: {whisper_model} | LLM: {llm_model}"
        )

        # Phone audio queue — registered by WebServer when phone connects
        self._audio_queue: queue.Queue | None = None
        self._audio_lock  = threading.Lock()
        # Set by WebServer on 'force_listen' SocketIO event (arc reactor tap)
        self._force_listen = threading.Event()

    # ── Public API ────────────────────────────────────────────────────────────

    def thread_factory(self) -> threading.Thread:
        """Build a fresh non-daemon Thread that runs the pipeline loop.

        Used by ThreadSupervisor so a crashed pipeline thread can be replaced.
        Each call returns a brand-new (un-started) Thread.
        """
        return threading.Thread(
            target=self._loop, daemon=False, name="voice-pipeline"
        )

    def start(self) -> None:
        """Spawn the pipeline as a daemon thread and return immediately."""
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="voice-pipeline"
        )
        self._thread.start()
        log.info("[PIPELINE] Background thread started.")

    def set_audio_queue(self, q: queue.Queue) -> None:
        """Called by WebServer when phone connects and starts streaming audio."""
        with self._audio_lock:
            self._audio_queue = q
        log.info("[PIPELINE] Phone audio queue registered.")

    def clear_audio_queue(self) -> None:
        """Called by WebServer when phone disconnects — fall back to laptop mic."""
        with self._audio_lock:
            self._audio_queue = None
        log.info("[PIPELINE] Phone audio queue cleared, reverting to laptop mic.")

    def trigger_force_listen(self) -> None:
        """Called by WebServer on 'force_listen' event — skips wake word."""
        self._force_listen.set()
        log.info("[PIPELINE] Force-listen event set.")

    # ── Pipeline loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        self.conversation_active = False
        if self._enable_wake_word:
            self.tts.speak(
                f"Hey, I'm jarvis. Say {self.wakeword.spoken_name} to wake me.",
                block=True,
            )
        else:
            self.tts.speak(
                "Hey, I'm jarvis. Hold space to talk.", block=True
            )

        while True:
            try:
                if not self.conversation_active:
                    # Wait for wake word or force_listen
                    if self._force_listen.is_set():
                        self._force_listen.clear()
                        log.info("[PIPELINE] Force-listen triggered from phone.")
                        # PTT path: one-shot, no welcome banter
                        self._conversation_cycle()
                        self.conversation_active = False
                        self._force_listen.clear()
                        continue
                    elif not self._enable_wake_word:
                        # Push-to-talk mode: nothing to listen for until the
                        # spacebar or the app tap sets force_listen.
                        self._force_listen.wait(timeout=0.05)
                        continue
                    else:
                        try:
                            with self._audio_lock:
                                aq = self._audio_queue
                            if aq is not None:
                                # Phone connected — listen for wake word on phone audio.
                                # PTT tap (force_listen) interrupts and falls through.
                                detected = self.wakeword.wait_for_wakeword_from_queue(
                                    aq, stop_event=self._force_listen
                                )
                                if not detected:
                                    continue
                            else:
                                # No phone: listen on the laptop mic. This branch
                                # used to just poll and continue, so a laptop-only
                                # run never reacted to the wake word at all.
                                detected = self.wakeword.wait_for_wakeword(
                                    stop_event=self._force_listen
                                )
                                if not detected:
                                    continue
                        except Exception as e:
                            log.error("[PIPELINE] Wake word failed, disabling: %s", e)
                            self._enable_wake_word = False
                            self.tts.speak("Wake word failed. Tap the arc reactor to talk.", block=True)
                            continue
                # ── One-shot conversation ──────────────────────────────────
                # After wake (or PTT tap), run one cycle then return to wake-wait.
                self._conversation_cycle()
                self.conversation_active = False
                self._force_listen.clear()
                continue
            except Exception as exc:
                log.error("[PIPELINE] Unhandled error: %s", exc, exc_info=True)
                self.tts.speak("I hit an error. Ready again.")

    def _conversation_cycle(self) -> None:
        # Only run within active conversation mode

        # ── 0. Correlation ID for this cycle ──────────────────────────────────
        corr_id = uuid4().hex[:12]
        set_corr_id(corr_id)
        log.info("[PIPELINE] Conversation cycle started  corr_id=%s", corr_id)

        # ── 1. Transcribe — phone queue or laptop mic ─────────────────────────
        with self._audio_lock:
            aq = self._audio_queue

        # PTT: spacebar gate only for laptop mic. Phone tap = single-shot VAD window.
        ptt_cb = None
        if not self._enable_wake_word and aq is None:
            ptt_cb = lambda: self._state.ptt_active

        text = self.stt.listen_from_queue(aq, ptt_callback=ptt_cb) if aq is not None else self.stt.listen(ptt_callback=ptt_cb)

        if not text:
            # Only show "didn't catch that" if we were actually expecting speech.
            # In PTT mode, a quick tap-release might return empty without annoyance.
            if self._enable_wake_word:
                self.tts.speak("I didn't catch that — try again.")
            return

        # Trust boundary: the STT backend is swappable and only promised to
        # return text. Coerce rather than letting a non-str crash the cycle.
        if not isinstance(text, str):
            log.warning("[PIPELINE] STT returned %s, not str; ignoring", type(text).__name__)
            return

        text_lower = text.lower()
        # End conversation if user says bye
        if any(word in text_lower for word in ["bye", "goodbye"]):
            self.conversation_active = False
            self.tts.speak(
                f"Goodbye. Say {self.wakeword.spoken_name} to wake me again.",
                block=False,
            )
            return

        # ── 3. Custom responses ───────────────────────────────────────────────
        for pattern, reply in CUSTOM_RESPONSES_COMPILED:
            if pattern.search(text_lower):
                log.info("[PIPELINE] Custom match %r", pattern.pattern)
                self._state.last_heard      = text
                self._state.jarvis_response = reply
                self.tts.speak(reply, block=False)
                return

        # ── 4. Emergency fast path ────────────────────────────────────────────
        words = set(text_lower.split())
        if words & EMERGENCY_KEYWORDS:
            log.info("[PIPELINE] Emergency keyword: %r", text)
            self.cmd_queue.clear()
            self._state.mode = "IDLE"
            self.tts.speak("Stopping now.", block=False)
            self.conversation_active = False  # End conversation on emergency
            return

        # ── 5. Visual context ─────────────────────────────────────────────────
        snapshot = self._state.snapshot()

        # ── 6. LLM ───────────────────────────────────────────────────────────
        print(f"[PIPELINE] Sending to LLM: '{text}'")
        result  = self.llm.parse(text, snapshot, corr_id=corr_id)
        speech  = result.get("speech", "")
        actions = result.get("actions", [])

        if speech:
            print(f"[jarvis] {speech}")

        # ── Update state for phone UI ─────────────────────────────────────────
        self._state.last_heard      = text
        self._state.jarvis_response = speech if speech else ""

        if speech:
            self.tts.speak(speech, block=False)

        if actions:
            self.cmd_queue.push_all(actions, corr_id=corr_id)


def voice_pipeline_thread_factory(pipeline: "VoicePipeline"):
    """Module-level helper bound to a `VoicePipeline` instance.

    Returns a callable suitable for `ThreadSupervisor.register(name, factory)`.
    """
    return pipeline.thread_factory
