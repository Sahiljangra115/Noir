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
import select
from typing import Optional

log = logging.getLogger(__name__)


# ── Intent / steer → single-char command maps ─────────────────────────────────

# VLA high-level intents (from Moondream)
INTENT_MAP: dict[str, str] = {
    "FOLLOW": "F",
    "SEARCH": "R",   # rotate in place to scan the room
    "STOP":   "S",
    "AVOID":  "B",   # back away from obstacle
}

# LFR steer strings (from tracker.LineFollower)
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
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Set socket timeout to prevent indefinite blocking
        self._server.settimeout(_SOCKET_TIMEOUT_S)
        self._server.bind((self.host, self.port))
        self._server.listen(1)
        log.info("[COMMS] Waiting for ESP32 on %s:%d …", self.host, self.port)
        print(f"[COMMS] Waiting for ESP32 on {self.host}:{self.port} …")

        # Use polling approach to avoid indefinite blocking
        while True:
            try:
                ready, _, _ = select.select([self._server], [], [], _SOCKET_TIMEOUT_S)
                if ready:
                    self._client, addr = self._server.accept()
                    break
            except (socket.timeout, OSError):
                # Allow interruption and continue polling
                continue

        # Configure client socket for low-latency operation
        self._client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._client.settimeout(_SEND_TIMEOUT_S)
        log.info("[COMMS] ESP32 connected from %s", addr)
        print(f"[COMMS] ESP32 connected from {addr}")

    def close(self) -> None:
        """Gracefully close both server and client sockets."""
        for sock in (self._client, self._server):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self._client = self._server = None
        print("[COMMS] Sockets closed.")

    # ── Command sending ───────────────────────────────────────────────────────

    def send(self, cmd: str) -> bool:
        """
        Send a single-character command to the ESP32.
        Returns True on success. Uses non-blocking I/O with timeout to prevent
        CV loop blocking. Silently drops duplicate commands to reduce noise.
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

        if cmd == self._last_cmd:
            return True               # de-duplicate; ESP32 keeps last command

        try:
            # Use select to check if socket is writable before sending
            _, writable, error = select.select([], [self._client], [self._client], _SEND_TIMEOUT_S)

            if error:
                log.warning("[COMMS] Socket error detected")
                self._client = None  # Mark as disconnected
                return False

            if writable:
                self._client.sendall(cmd.encode("utf-8"))
                self._last_cmd = cmd
                return True
            else:
                # Socket not ready for writing within timeout
                log.debug("[COMMS] Send timeout - socket not ready")
                return False

        except (BrokenPipeError, ConnectionResetError, OSError, socket.timeout) as exc:
            log.warning("[COMMS] Send failed (%s). ESP32 disconnected?", exc)
            self._client = None  # Mark as disconnected
            return False
        except Exception as exc:
            log.error("[COMMS] Unexpected error in send: %s", exc)
            self._client = None  # Mark as disconnected on any error
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
