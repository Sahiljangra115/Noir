"""
robot_comms.py – Hardware Bridge
─────────────────────────────────
TCP socket server running on the laptop.  The ESP32 connects as a client
and waits for single-byte ASCII commands:

    'F'  – Forward
    'B'  – Backward
    'L'  – Turn Left
    'R'  – Turn Right
    'S'  – Stop

The ESP32 is a "dumb client": it does no thinking, only executes pins.

Usage (imported by main.py):
    comms = RobotComms(host="0.0.0.0", port=9999)
    comms.wait_for_esp32()          # blocks until ESP32 connects
    comms.send("F")                 # UTF-8 single char
    comms.close()
"""

import socket
import logging
import random
import select
import threading
import time
from typing import Optional

from backend.config import config

log = logging.getLogger(__name__)


# ── Intent / steer → single-char command maps ─────────────────────────────────

# VLA high-level intents (tracker/vision_processor may emit these)
INTENT_MAP: dict[str, str] = {
    "FOLLOW": "F",
    "SEARCH": "R",   # rotate in place to scan the room
    "STOP":   "S",
    "AVOID":  "B",   # back away from obstacle
}

# LFR steer strings (from tracker.HybridLineFollower.scan)
LFR_MAP: dict[str, str] = {
    "STRAIGHT": "F",
    "LEFT":     "L",
    "RIGHT":    "R",
    "LOST":     "S",   # lost line → hold position
}

# Safe-distance thresholds (fraction of total frame area occupied by bbox)
_AREA_TOO_CLOSE = 0.40   # > 40 % → STOP (too close)
_AREA_TOO_FAR   = 0.15   # < 15 % → FORWARD (too far)
_ANGLE_DEADZONE = 5.0    # degrees – ignore tiny rotation jitter

# Socket timeout settings for non-blocking operations
_SOCKET_TIMEOUT_S = 0.1   # 100ms timeout for socket operations
_SEND_TIMEOUT_S = 0.05    # 50ms timeout for send operations

# Duplicate commands are suppressed to keep the link quiet, but not forever:
# the ESP32 arms a LINK_TIMEOUT_S failsafe that cuts the motors when nothing
# arrives. Re-sending the unchanged command at this interval keeps a steady
# drive alive while still tripping the failsafe if the brain dies.
# Must stay well below LINK_TIMEOUT_S in backend/esp32/main/main.c (2 s).
_KEEPALIVE_S = 0.5

# Poll interval used while the listening socket cannot be bound (e.g. the port
# is still held by a previous run). Without it the accept loop spins at 100% CPU.
_BIND_RETRY_S = 1.0


class RobotComms:
    """
    TCP server side of the laptop ↔ ESP32 link.

    The server listens on `host:port`.  The ESP32 initiates the connection,
    so the laptop must be reachable at a static / well-known IP on the local
    network (or via USB-tethering with a fixed IP).

    Supports context manager protocol for proper resource cleanup.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9999) -> None:
        # Input validation
        if not isinstance(host, str) or not host:
            raise ValueError(f"Invalid host: {host!r}")
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError(f"Invalid port: {port!r}")

        self.host     = host
        self.port     = port
        self._server: Optional[socket.socket]  = None
        self._client: Optional[socket.socket]  = None
        self._last_cmd: str = ""
        self._last_sent_at: float = 0.0

        # Reconnect supervision
        self._stop_event: threading.Event = threading.Event()
        self._reconnect_thread: Optional[threading.Thread] = None
        self._reconnect_attempt: int = 0
        self._reconnect_lock = threading.Lock()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.close()
        return False  # Don't suppress exceptions

    # ── Server lifecycle ──────────────────────────────────────────────────────

    def wait_for_esp32(self) -> None:
        """
        Bind the server socket and block until the ESP32 connects.
        Call this once at startup before entering the main loop.
        """
        self._ensure_server_bound()
        log.info("[COMMS] Waiting for ESP32 on %s:%d …", self.host, self.port)
        print(f"[COMMS] Waiting for ESP32 on {self.host}:{self.port} …")

        # Use polling approach to avoid indefinite blocking
        while not self._stop_event.is_set():
            if self._attempt_connect():
                return
            # _attempt_connect polls the listening socket with its own timeout,
            # so the loop is already paced while bound. When the bind itself
            # failed there is no socket to poll, so back off explicitly.
            if self._server is None:
                self._stop_event.wait(_BIND_RETRY_S)

    def _ensure_server_bound(self) -> None:
        """Bind/re-bind the listening socket if not already bound."""
        if self._server is not None:
            return
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.settimeout(_SOCKET_TIMEOUT_S)
        srv.bind((self.host, self.port))
        srv.listen(1)
        self._server = srv

    def _attempt_connect(self) -> bool:
        """One non-blocking accept poll. Returns True on successful connect."""
        try:
            self._ensure_server_bound()
        except OSError as exc:
            log.warning("[COMMS] Could not bind listening socket: %s", exc)
            return False

        try:
            ready, _, _ = select.select([self._server], [], [], _SOCKET_TIMEOUT_S)
            if not ready:
                return False
            client, addr = self._server.accept()
        except (socket.timeout, OSError) as exc:
            log.debug("[COMMS] accept poll error: %s", exc)
            return False

        # Configure client socket for low-latency operation
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client.settimeout(_SEND_TIMEOUT_S)
        self._client = client
        self._reconnect_attempt = 0
        # A reconnected ESP32 has rebooted into a stopped state and remembers
        # nothing. Clearing the dedupe marker makes the next command — even if
        # identical to the pre-disconnect one — actually go out on the wire.
        self._last_cmd = ""
        self._last_sent_at = 0.0
        log.info("[COMMS] ESP32 connected from %s", addr)
        print(f"[COMMS] ESP32 connected from {addr}")
        return True

    def _schedule_reconnect(self) -> None:
        """Spawn the reconnect loop thread if not already running."""
        with self._reconnect_lock:
            if self._stop_event.is_set():
                return
            if self._reconnect_thread is not None and self._reconnect_thread.is_alive():
                return
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop,
                name="esp32-reconnect",
                daemon=True,
            )
            self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """Backoff loop that retries `_attempt_connect` until reconnected."""
        log.info("[COMMS] Reconnect loop started (attempt=%d)", self._reconnect_attempt)
        while not self._stop_event.is_set() and self._client is None:
            delay = min(
                config.ESP32_RECONNECT_BASE_S * (2 ** self._reconnect_attempt)
                + random.uniform(0, 1),
                config.ESP32_RECONNECT_MAX_S,
            )
            log.info("[COMMS] Reconnect attempt %d in %.2fs", self._reconnect_attempt + 1, delay)
            # Sleep in small slices so stop() can interrupt promptly.
            woken = self._stop_event.wait(delay)
            if woken:
                return
            if self._attempt_connect():
                log.info("[COMMS] Reconnect succeeded.")
                return
            self._reconnect_attempt += 1

    def stop(self) -> None:
        """Signal shutdown, join reconnect thread, close sockets."""
        self._stop_event.set()
        thr = self._reconnect_thread
        if thr is not None and thr.is_alive():
            thr.join(timeout=2.0)
        self.close()

    def close(self) -> None:
        """Gracefully close both server and client sockets."""
        had_socket = self._client is not None or self._server is not None
        for sock in (self._client, self._server):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self._client = self._server = None
        self._last_cmd = ""
        self._last_sent_at = 0.0
        if had_socket:
            log.info("[COMMS] Sockets closed.")

    # ── Command sending ───────────────────────────────────────────────────────

    # Allow-list at the socket boundary: the five motor commands the firmware
    # in backend/esp32/main/main.c actually implements. Anything else would hit
    # the firmware's `default:` branch and halt the motors, so it is dropped here.
    _ALLOWED_CMDS = frozenset("FBLRS")

    def send(self, cmd: str, *, corr_id: str = "") -> bool:
        """
        Send a single-character command to the ESP32.
        Returns True on success. Uses non-blocking I/O with timeout to prevent
        CV loop blocking. Duplicate commands are suppressed for up to
        ``_KEEPALIVE_S`` and then re-sent, so the firmware's link failsafe sees
        a live brain without the CV loop flooding the socket at 20 Hz.
        """
        # Input validation
        if not cmd or not isinstance(cmd, str):
            log.warning("[COMMS] Invalid command type: %r", cmd)
            return False

        if not self._client:
            log.debug("[COMMS] No client connection available")
            return False

        try:
            cmd = cmd.upper()[0]          # safety: always one char, uppercase
        except (IndexError, AttributeError):
            log.warning("[COMMS] Invalid command format: %r", cmd)
            return False

        if cmd not in self._ALLOWED_CMDS:
            log.warning("[COMMS] Rejected command not in allow-list: %r", cmd)
            return False

        now = time.monotonic()
        if cmd == self._last_cmd and (now - self._last_sent_at) < _KEEPALIVE_S:
            return True               # de-duplicate; ESP32 keeps last command

        try:
            # Use select to check if socket is writable before sending
            _, writable, error = select.select([], [self._client], [self._client], _SEND_TIMEOUT_S)

            if error:
                log.warning("[COMMS] Socket error detected")
                self._client = None  # Mark as disconnected
                self._schedule_reconnect()
                return False

            if writable:
                self._client.sendall(cmd.encode("utf-8"))
                self._last_cmd = cmd
                self._last_sent_at = now
                if corr_id:
                    log.info("[COMMS] Sent %r  corr_id=%s", cmd, corr_id)
                return True
            else:
                # Socket not ready for writing within timeout
                log.debug("[COMMS] Send timeout - socket not ready")
                return False

        except (BrokenPipeError, ConnectionResetError, OSError, socket.timeout) as exc:
            log.warning("[COMMS] Send failed (%s). ESP32 disconnected?", exc)
            self._client = None  # Mark as disconnected
            self._schedule_reconnect()
            return False
        except Exception as exc:
            log.error("[COMMS] Unexpected error in send: %s", exc)
            self._client = None  # Mark as disconnected on any error
            self._schedule_reconnect()
            return False

    @property
    def connected(self) -> bool:
        return self._client is not None

    # ── Translation helpers ───────────────────────────────────────────────────

    @staticmethod
    def from_intent(intent: str) -> str:
        """Map a VLA high-level intent string → single-char command."""
        return INTENT_MAP.get(intent.upper(), "S")

    @staticmethod
    def from_lfr(steer: str) -> str:
        """Map a LineFollower steer string → single-char command."""
        return LFR_MAP.get(steer.upper(), "S")

    @staticmethod
    def from_human_bbox(
        bbox: tuple[int, int, int, int],
        frame_w: int,
        frame_h: int,
        rotate_deg: float = 0.0,
    ) -> str:
        """
        Safe-distance logic for human tracking.

        Priority:
          1. If bbox area > 40 % of frame → STOP  (too close, safety)
          2. If |rotate_deg| > _ANGLE_DEADZONE  → turn to centre target
          3. If bbox area < 15 % of frame → FORWARD (target too far)
          4. Otherwise → STOP / hold position (comfortable distance)
        """
        x1, y1, x2, y2 = bbox
        bbox_area  = (x2 - x1) * (y2 - y1)
        frame_area = frame_w * frame_h
        ratio = bbox_area / max(frame_area, 1)

        if ratio > _AREA_TOO_CLOSE:
            return "S"                         # safety stop

        if abs(rotate_deg) > _ANGLE_DEADZONE:
            return "R" if rotate_deg > 0 else "L"   # turn to face target

        if ratio < _AREA_TOO_FAR:
            return "F"                         # approach

        return "S"                             # comfortable distance – hold
