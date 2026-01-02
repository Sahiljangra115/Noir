"""
pipeline/voice_pipeline.py
───────────────────────────
Top-level orchestrator for the STT → LLM → TTS + Actions pipeline.

Flow on each activation
────────────────────────
1. WakeWordDetector blocks until "Jarvis" is heard (Porcupine)
   OR force_listen event is set (Flutter app arc reactor tap)
2. PiperTTS plays a short listening cue (blocking, so mic stays clean)
3. WhisperSTT records — from phone queue if connected, else laptop mic
4. CUSTOM_RESPONSES checked first — instant reply for known phrases
5. Emergency keyword check → immediate STOP if detected
6. Visual context (YOLO info) injected into LLM prompt
7. LLMParser sends to Gemma 3 4B → receives {speech, actions}
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

from .command_queue import CommandQueue
from .llm_parser    import EMERGENCY_KEYWORDS, LLMParser
from .stt           import WhisperSTT
from .tts           import PiperTTS
from .wake_word     import WakeWordDetector

log = logging.getLogger(__name__)

_DEFAULT_WAKEWORD = "jarvis"

# Pre-compile regex patterns for efficiency
CUSTOM_RESPONSES_COMPILED = [
    (re.compile(r"\b(who made|who built|who created|who programmed) you\b"),
        "I was built by my creator as a final year engineering project. "
        "They designed me to be an autonomous robot assistant."),

    (re.compile(r"\bwhat (is your name|are you called|do (i|we) call you)\b"),
        "I'm JARVIS. Short for Just A Rather Very Intelligent System."),

    (re.compile(r"\bwhat (can you do|are your capabilities|are you capable of)\b"),
        "I can follow lines, track people, navigate autonomously using my camera, "
        "respond to voice commands, and hold a conversation. "
        "Pretty good for a final year project, right?"),

    (re.compile(r"\b(are you|jarvis are you) (alive|conscious|sentient)\b"),
        "I'm not conscious, no. I'm an AI running on a laptop. "
        "But I do my best to be useful."),

    (re.compile(r"\b(hello|hi|hey)( there| jarvis)?\b"),
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
        wakeword:      str = _DEFAULT_WAKEWORD,
        whisper_model: str = "tiny",
        llm_model:     str = "gemma3:4b-it-q4_K_M",
    ) -> None:
        self._state  = state
        self._thread = None

        print("[PIPELINE] Initialising components…")

        self.wakeword  = WakeWordDetector(keyword=wakeword)
        self.stt       = WhisperSTT(model_size=whisper_model, device="auto")
        self.tts       = PiperTTS()
        self.llm       = LLMParser(model=llm_model)
        self.cmd_queue = CommandQueue(comms=comms, robot_state=state)

        print(
            f"[PIPELINE] Ready — wake word: '{wakeword}' | "
            f"Whisper: {whisper_model} | LLM: {llm_model}"
        )

        # Phone audio queue — registered by WebServer when phone connects
        self._audio_queue: queue.Queue | None = None
        self._audio_lock  = threading.Lock()
        # Set by WebServer on 'force_listen' SocketIO event (arc reactor tap)
        self._force_listen = threading.Event()

    # ── Public API ────────────────────────────────────────────────────────────

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
        self.tts.speak(
            "Hey, I'm JARVIS. Say Jarvis whenever you need me.", block=True
        )

        while True:
            try:
                self._single_cycle()
            except Exception as exc:
                log.error("[PIPELINE] Unhandled error: %s", exc, exc_info=True)
                self.tts.speak("I hit an error. Ready again.")

    def _single_cycle(self) -> None:
        # ── 1. Wait for wake word OR arc reactor tap ──────────────────────────
        if self._force_listen.is_set():
            self._force_listen.clear()
            log.info("[PIPELINE] Force-listen triggered from phone.")
        else:
            self.wakeword.wait_for_wakeword()

        self.tts.speak("hello?", block=False)
        time.sleep(0.15)

        # ── 2. Transcribe — phone queue or laptop mic ─────────────────────────
        with self._audio_lock:
            aq = self._audio_queue

        text = self.stt.listen_from_queue(aq) if aq is not None else self.stt.listen()

        if not text:
            self.tts.speak("I didn't catch that — try again.")
            return

        # ── 3. Custom responses ───────────────────────────────────────────────
        text_lower = text.lower()
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
            return

        # ── 5. Visual context ─────────────────────────────────────────────────
        snapshot = self._state.snapshot()

        # ── 6. LLM ───────────────────────────────────────────────────────────
        print(f"[PIPELINE] Sending to LLM: '{text}'")
        result  = self.llm.parse(text, snapshot)
        speech  = result.get("speech", "")
        actions = result.get("actions", [])

        if speech:
            print(f"[JARVIS] {speech}")

        # ── Update state for phone UI ─────────────────────────────────────────
        self._state.last_heard      = text
        self._state.jarvis_response = speech if speech else ""

        # ── 7. Speak reply ────────────────────────────────────────────────────
        if speech:
            self.tts.speak(speech, block=False)

        # ── 8. Execute actions ────────────────────────────────────────────────
        if actions:
            self.cmd_queue.push_all(actions)
