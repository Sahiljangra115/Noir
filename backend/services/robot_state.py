"""
pipeline/robot_state.py
────────────────────────
Single shared-state object that every thread reads/writes.
Protected by a reentrant lock so CV loop, command queue, and
voice pipeline can all touch it safely.
"""

import threading


class RobotState:
    """
    Thread-safe bag of robot state.

    Attributes
    ----------
    mode        : current operating mode (str)
                  "IDLE" | "LFR" | "HUMAN" | "VLA" | "MANUAL" | "GOTO"
    last_cmd    : last single-char command sent to ESP32 (str)
    goto_target : object label for GOTO mode (str | None)
    yolo_info   : latest YOLO detections as a human-readable string,
                  injected by the CV loop every frame and read by the LLM
                  to give it visual context.
    phone_connected : True when Flutter app has an active WebSocket connection
    imu         : latest IMU data from phone {accel, gyro, orientation}
    gps         : latest GPS data from phone {lat, lon, alt, speed}
    last_heard  : last transcribed user utterance (shown in phone UI)
    jarvis_response : last jarvis speech reply (shown in phone UI)
    camera_device : camera device identifier for audio routing decision
    """

    def __init__(self) -> None:
        self._lock           = threading.RLock()
        self._mode           : str        = "IDLE"
        self._last_cmd       : str        = "S"
        self._goto_target    : str | None = None
        self._yolo_info      : str        = "no detections"
        self._phone_connected: bool       = False
        self._imu            : dict       = {}
        self._gps            : dict       = {}
        self._last_heard     : str        = ""
        self._jarvis_response: str        = ""
        self._camera_device  : str        = ""

    # ── mode ─────────────────────────────────────────────────────────────────
    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        with self._lock:
            self._mode = value

    # ── last_cmd ─────────────────────────────────────────────────────────────
    @property
    def last_cmd(self) -> str:
        with self._lock:
            return self._last_cmd

    @last_cmd.setter
    def last_cmd(self, value: str) -> None:
        with self._lock:
            self._last_cmd = value

    # ── goto_target ──────────────────────────────────────────────────────────
    @property
    def goto_target(self) -> str | None:
        with self._lock:
            return self._goto_target

    @goto_target.setter
    def goto_target(self, value: str | None) -> None:
        with self._lock:
            self._goto_target = value

    # ── yolo_info ────────────────────────────────────────────────────────────
    @property
    def yolo_info(self) -> str:
        with self._lock:
            return self._yolo_info

    @yolo_info.setter
    def yolo_info(self, value: str) -> None:
        with self._lock:
            self._yolo_info = value

    # ── phone_connected ───────────────────────────────────────────────────────
    @property
    def phone_connected(self) -> bool:
        with self._lock:
            return self._phone_connected

    @phone_connected.setter
    def phone_connected(self, value: bool) -> None:
        with self._lock:
            self._phone_connected = value

    # ── imu ──────────────────────────────────────────────────────────────────
    @property
    def imu(self) -> dict:
        with self._lock:
            return dict(self._imu)

    @imu.setter
    def imu(self, value: dict) -> None:
        with self._lock:
            self._imu = value

    # ── gps ──────────────────────────────────────────────────────────────────
    @property
    def gps(self) -> dict:
        with self._lock:
            return dict(self._gps)

    @gps.setter
    def gps(self, value: dict) -> None:
        with self._lock:
            self._gps = value

    # ── last_heard ────────────────────────────────────────────────────────────
    @property
    def last_heard(self) -> str:
        with self._lock:
            return self._last_heard

    @last_heard.setter
    def last_heard(self, value: str) -> None:
        with self._lock:
            self._last_heard = value

    # ── jarvis_response ───────────────────────────────────────────────────────
    @property
    def jarvis_response(self) -> str:
        with self._lock:
            return self._jarvis_response

    @jarvis_response.setter
    def jarvis_response(self, value: str) -> None:
        with self._lock:
            self._jarvis_response = value

    # ── camera_device ─────────────────────────────────────────────────────────
    @property
    def camera_device(self) -> str:
        with self._lock:
            return self._camera_device

    @camera_device.setter
    def camera_device(self, value: str) -> None:
        with self._lock:
            self._camera_device = value

    def snapshot(self) -> dict:
        """Return a plain dict copy – safe to pass across threads."""
        with self._lock:
            return {
                "mode":             self._mode,
                "last_cmd":         self._last_cmd,
                "goto_target":      self._goto_target,
                "yolo_info":        self._yolo_info,
                "phone_connected":  self._phone_connected,
                "imu":              dict(self._imu),
                "gps":              dict(self._gps),
                "last_heard":       self._last_heard,
                "jarvis_response":  self._jarvis_response,
                "camera_device":    self._camera_device,
            }
