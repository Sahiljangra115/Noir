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

``goto`` and ``arm`` used to live here too. Neither had an executor behind it:
``goto`` set a mode the CV loop does not dispatch on (so every frame logged
"Unknown mode" and stopped), and ``arm`` pushed characters the ESP32 firmware
treats as unknown and answers with a motor halt. Both are gone from the LLM
schema as well — see backend/services/llm_parser.py.
"""

import logging
import queue
import threading
import time

from backend.config import config

log = logging.getLogger(__name__)

# Modes the CV loop in backend/main.py dispatches on. A mode action naming
# anything else is rejected rather than parked in an unhandled state.
_VALID_MODES = frozenset({"LFR", "HUMAN_TRACK", "VLA", "MANUAL", "IDLE"})


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
        self._q: queue.Queue = queue.Queue(maxsize=config.CMD_QUEUE_MAX)
        self._stop_event     = threading.Event()

        self._thread = threading.Thread(
            target=self._executor_loop, daemon=True, name="cmd-queue"
        )
        self._thread.start()
        log.info("[QUEUE] Executor thread started.")

    def executor_thread_factory(self) -> threading.Thread:
        """Return a fresh non-daemon Thread running the executor loop.

        For ThreadSupervisor registration. Each call returns a new (un-started)
        Thread so a crashed executor can be replaced.
        """
        return threading.Thread(
            target=self._executor_loop, daemon=False, name="cmd-queue"
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def _put_drop_oldest(self, action: dict) -> None:
        """Non-blocking enqueue with drop-oldest eviction when full."""
        try:
            self._q.put_nowait(action)
        except queue.Full:
            # Evict oldest then retry. The evict + put pair is not strictly
            # atomic across producers, but the queue still respects maxsize
            # (a concurrent put will hit Full and evict its own oldest).
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            log.warning(
                "[QUEUE] dropped oldest action; queue full at %d",
                self._q.maxsize,
            )
            try:
                self._q.put_nowait(action)
            except queue.Full:
                # Pathological case — another producer refilled the queue
                # between the get and put. Drop the new action rather than
                # block, and surface it loudly.
                log.error("[QUEUE] still full after eviction; dropping new action")

    def push(self, action: dict, *, corr_id: str = "") -> None:
        """Enqueue a single action token."""
        log.info("[QUEUE] Enqueue  corr_id=%s  action=%s", corr_id, action)
        self._put_drop_oldest(action)

    def push_all(self, actions: list[dict], *, corr_id: str = "") -> None:
        """Enqueue a list of action tokens (executed in order)."""
        log.info("[QUEUE] Enqueue %d action(s)  corr_id=%s", len(actions), corr_id)
        for action in actions:
            self._put_drop_oldest(action)

    def clear(self) -> None:
        """
        Drain the queue immediately (used by emergency stop).
        The currently-executing action finishes naturally, but no
        further actions will run.
        """
        cleared = 0
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
            cleared += 1
        if cleared:
            log.info("[QUEUE] Cleared %d pending action(s).", cleared)

    # ── Executor ───────────────────────────────────────────────────────────────

    def _executor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                action = self._q.get(timeout=0.05)
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
            if value not in _VALID_MODES:
                log.warning("[QUEUE] Rejected unknown mode %r; staying in %s",
                            value, self._state.mode)
                return
            self._state.mode = value
            log.info("[QUEUE] Mode → %s", value)

        # ── timed move ────────────────────────────────────────────────────────
        elif kind == "move":
            cmd      = action.get("cmd", "S").upper()
            duration = float(action.get("duration", 1.0))
            duration = max(0.1, min(duration, config.MOVE_MAX_DURATION_S))

            prev_mode = self._state.mode
            self._state.mode = "MANUAL"     # freeze CV loop during timed move
            # The CV loop drives last_cmd while in MANUAL, so it has to agree
            # with what we just put on the wire or the next frame reverts it.
            self._state.last_cmd = cmd

            self._comms.send(cmd)
            log.info("[QUEUE] Moving %s for %.1fs", cmd, duration)
            time.sleep(duration)
            self._comms.send("S")           # stop after timed move
            self._state.last_cmd = "S"

            # Restore the pre-move mode, but only if nothing else claimed the
            # robot while we were sleeping. An emergency stop sets IDLE mid-move
            # and must not be undone by a stale restore.
            if self._state.mode == "MANUAL" and prev_mode != "MANUAL":
                self._state.mode = prev_mode

        else:
            log.warning("[QUEUE] Unknown action type: %s", kind)
