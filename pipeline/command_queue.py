"""
pipeline/command_queue.py
──────────────────────────
Thread-safe action token executor.

Receives action dicts from the LLM parser (via voice_pipeline) and
executes them in order on a dedicated background thread.  The main
CV loop reads `robot_state.mode` and acts accordingly — this queue
only needs to write to the state and send raw socket commands.

Action types handled
────────────────────
  mode   → set robot_state.mode
  move   → send raw char for N seconds, then send 'S'
  goto   → set mode=GOTO + target label (CV loop navigates)
  arm    → send arm char command (G/O/U/D) to ESP32
"""

import logging
import queue
import threading
import time

log = logging.getLogger(__name__)

# Arm command → single-char ESP32 code
_ARM_MAP: dict[str, str] = {
    "GRAB":    "G",
    "RELEASE": "O",
    "UP":      "U",
    "DOWN":    "D",
}


class CommandQueue:
    """
    FIFO queue consumed by a single daemon executor thread.

    Parameters
    ----------
    comms       : RobotComms instance (for sending socket commands)
    robot_state : RobotState instance (shared state bag)
    """

    def __init__(self, comms, robot_state) -> None:
        self._comms   = comms
        self._state   = robot_state
        self._q: queue.Queue = queue.Queue()
        self._stop_event     = threading.Event()

        self._thread = threading.Thread(
            target=self._executor_loop, daemon=True, name="cmd-queue"
        )
        self._thread.start()
        log.info("[QUEUE] Executor thread started.")

    # ── Public API ─────────────────────────────────────────────────────────────

    def push(self, action: dict) -> None:
        """Enqueue a single action token."""
        self._q.put(action)

    def push_all(self, actions: list[dict]) -> None:
        """Enqueue a list of action tokens (executed in order)."""
        for action in actions:
            self._q.put(action)

    def clear(self) -> None:
        """
        Drain the queue immediately (used by emergency stop).
        The currently-executing action finishes naturally, but no
        further actions will run.
        """
        cleared = 0
        while not self._q.empty():
            try:
                self._q.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        if cleared:
            log.info("[QUEUE] Cleared %d pending action(s).", cleared)

    # ── Executor ───────────────────────────────────────────────────────────────

    def _executor_loop(self) -> None:
        while True:
            try:
                action = self._q.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self._execute(action)
            except Exception as exc:
                log.error("[QUEUE] Action failed: %s  action=%s", exc, action)
            finally:
                self._q.task_done()

    def _execute(self, action: dict) -> None:
        kind = action.get("type", "")
        log.info("[QUEUE] Executing: %s", action)

        # ── mode change ───────────────────────────────────────────────────────
        if kind == "mode":
            value = action.get("value", "IDLE").upper()
            self._state.mode = value
            log.info("[QUEUE] Mode → %s", value)

        # ── timed move ────────────────────────────────────────────────────────
        elif kind == "move":
            cmd      = action.get("cmd", "S").upper()
            duration = float(action.get("duration", 1.0))
            duration = max(0.1, min(duration, 30.0))   # clamp 0.1–30 s

            prev_mode = self._state.mode
            self._state.mode = "MANUAL"     # freeze CV loop during timed move

            self._comms.send(cmd)
            log.info("[QUEUE] Moving %s for %.1fs", cmd, duration)
            time.sleep(duration)
            self._comms.send("S")           # stop after timed move

            # Restore the mode that was active before unless it was also MANUAL
            if prev_mode != "MANUAL":
                self._state.mode = prev_mode

        # ── goal navigation ───────────────────────────────────────────────────
        elif kind == "goto":
            target = action.get("target", "object")
            self._state.goto_target = target
            self._state.mode = "GOTO"
            log.info("[QUEUE] GOTO → '%s'  (CV loop navigates)", target)
            # The CV loop handles the actual driving; queue doesn't block here.
            # When the CV loop signals arrival it will set mode back to IDLE.

        # ── arm control ───────────────────────────────────────────────────────
        elif kind == "arm":
            cmd_str = action.get("cmd", "RELEASE").upper()
            char    = _ARM_MAP.get(cmd_str, "O")
            self._comms.send(char)
            log.info("[QUEUE] Arm → %s (%s)", cmd_str, char)
            time.sleep(1.5)    # allow servo time to move

        else:
            log.warning("[QUEUE] Unknown action type: %s", kind)
