"""
main.py – JARVIS Robot Brain
─────────────────────────────
Orchestrates the full pipeline:

    Phone camera (scrcpy → v4l2) → OpenCV frame
        │
        ├─ [LFR mode]         LineFollower (tracker.py)
        ├─ [HUMAN mode]       YOLOv8 HumanDetector (tracker.py)
        ├─ [VLA mode]         Moondream via Ollama (vision_processor.py)
        └─ [MANUAL mode]      Direct voice command pass-through
                │
        RobotComms (robot_comms.py)
                │
       TCP socket → ESP32 → motor pins

Voice commands come from the phone mic (streamed over WebSocket to
WhisperSTT), or from the laptop mic when the phone is not connected.
TTS output plays on the phone speaker when connected; laptop speaker otherwise.

Run:
    # With phone connected (recommended):
    scrcpy --video-source=camera --camera-facing=back \
           --v4l2-sink=/dev/video2 --no-audio --max-fps 30
    python main.py

    # Without ESP32 (CV + voice only):
    python main.py --no-socket

    # Override camera device:
    python main.py --device /dev/video4

    # Use laptop webcam for testing:
    python main.py --device 0
"""

import argparse
import logging
import sys
import time
import os
import threading
from typing import Optional
from collections import deque

import cv2
import numpy as np
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# ── Core modules ─────────────────────────────────────────────────────────────
from backend.services.robot_state import RobotState
from backend.services.voice_pipeline import VoicePipeline
from backend.esp32.robot_comms import RobotComms
from vision_processor        import GemmaVLAProcessor
from web_server              import WebServer
from utils.cv_text           import draw_text, draw_detection_box

# ── CV / tracking ─────────────────────────────────────────────────────────────
from tracker import (
    HumanDetector,
    HybridLineFollower,  # Use Hybrid for ML+fallback
    EMATracker,
    compute_focal,
    pixel_offset_to_angle,
    draw_line_overlay,
    HFOV_DEG,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

from enum import Enum, auto

class RobotMode(Enum):
    LFR         = "LFR"
    HUMAN_TRACK = "HUMAN_TRACK"
    VLA         = "VLA"
    MANUAL      = "MANUAL"
    IDLE        = "IDLE"

# Keep these for compatibility if they are used elsewhere by name
MODE_LFR    = RobotMode.LFR.value
MODE_HUMAN  = RobotMode.HUMAN_TRACK.value
MODE_VLA    = RobotMode.VLA.value
MODE_MANUAL = RobotMode.MANUAL.value
MODE_IDLE   = RobotMode.IDLE.value

# ── Timing ────────────────────────────────────────────────────────────────────
LOOP_SLEEP_S = 0.05   # 20 fps cap
VLA_QUERY_S  = 2.0
ANGLE_DEAD   = 5.0

# ── HUD colours (BGR) ─────────────────────────────────────────────────────────
_CLR_GREEN  = (0,  200,   0)
_CLR_YELLOW = (0,  220, 220)
_CLR_RED    = (0,   50, 220)
_CLR_BLUE   = (230, 130,  0)
_CLR_WHITE  = (240, 240, 240)

MODE_COLOURS = {
    MODE_LFR:    _CLR_GREEN,
    MODE_HUMAN:  _CLR_YELLOW,
    MODE_VLA:    _CLR_BLUE,
    MODE_MANUAL: _CLR_WHITE,
    MODE_IDLE:   _CLR_RED,
}

CMD_NAMES = {
    "F": "FORWARD", "B": "BACKWARD",
    "L": "LEFT",    "R": "RIGHT",
    "S": "STOP",
}


# ─────────────────────────── RobotBrain ──────────────────────────────────────

class RobotBrain:
    """Central coordinator for the entire bot with memory and performance optimizations."""

    def __init__(
        self,
        device:    str  = "/dev/video2",
        esp_host:  str  = "0.0.0.0",
        esp_port:  int  = 9999,
        web_port:  int  = 5000,
        use_socket: bool = True,
        use_web:    bool = True,
        vla_model:  str  = "gemma4-e2b-nothink:latest",
        wake_sens:  float = 0.6,
        stt_threshold: int = 850,
        use_wake_word: bool = True,
    ) -> None:
        self.device     = device
        self.use_socket = use_socket
        self.use_web    = use_web
        self.use_wake_word = use_wake_word

        # ── Shared thread-safe state ──────────────────────────────────────
        self._state = RobotState()

        # ── Hardware bridge (ESP32) ───────────────────────────────────────
        self.comms = RobotComms(host=esp_host, port=esp_port)

        # ── Vision / CV components ────────────────────────────────────────
        self.human_det = HumanDetector()
        self.line_det  = HybridLineFollower()  # Uses ML (if present) and falls back to OpenCV
        self.ema       = EMATracker()
        self.vla       = GemmaVLAProcessor(model=vla_model)

        # ── Async VLA state for non-blocking inference ──────────────────
        self._vla_lock = threading.Lock()
        self._vla_busy = False
        self._last_vla_resp = {"speech": "", "actions": []}

        # ── Web server (Flask-SocketIO) ────────────────────────────────────
        self._web = WebServer(
            state=self._state,
            comms=self.comms,
            port=web_port,
        )

        # ── Voice pipeline (STT → LLM → TTS → actions) ────────────────────
        self._pipeline = VoicePipeline(
            comms=self.comms,
            state=self._state,
            wake_sensitivity=wake_sens,
            stt_threshold=stt_threshold,
            enable_wake_word=use_wake_word,
        )

        # Wire TTS callback: when phone connected → phone speaker only
        if self.use_web:
            self._web.set_voice_pipeline(self._pipeline)

        # VLA timing
        self._last_vla: float = 0.0
        self._last_intent: str = "STOP"

        # focal length (set after first frame)
        self._focal_px: Optional[float] = None

        # Memory optimization: object pooling for frequent allocations
        self._frame_pool = deque(maxlen=3)  # Pool of reusable frame copies
        self._shape_cache = {}  # Cache frame shapes to avoid recalculation

    # ── Command routing ───────────────────────────────────────────────────────

    def _get_pooled_frame_copy(self, frame: np.ndarray) -> np.ndarray:
        """Get a frame copy using object pooling to reduce allocations."""
        frame_shape = frame.shape
        shape_key = frame_shape

        # Try to reuse a frame from the pool with matching shape
        for _ in range(len(self._frame_pool)):
            pooled_frame = self._frame_pool.popleft()
            if pooled_frame.shape == frame_shape:
                # Reuse existing frame - much faster than allocation
                np.copyto(pooled_frame, frame)
                return pooled_frame
            else:
                # Wrong shape, put it back and continue
                self._frame_pool.append(pooled_frame)

        # No suitable frame in pool, create new one
        return frame.copy()

    def _return_frame_to_pool(self, frame: np.ndarray) -> None:
        """Return frame to pool for reuse."""
        if len(self._frame_pool) < self._frame_pool.maxlen:
            self._frame_pool.append(frame)

    def _send(self, cmd: str) -> None:
        """Send command with error handling."""
        try:
            if self.use_socket:
                success = self.comms.send(cmd)
                if not success and self.comms.connected:
                    log.warning("[BRAIN] Command send failed but connection exists")
            elif cmd != self._state.last_cmd:
                print(f"[MOCK ] Would send: {cmd} ({CMD_NAMES.get(cmd, '?')})")
            self._state.last_cmd = cmd
        except Exception as exc:
            log.error("[BRAIN] Command send error: %s", exc)
            # Continue operation even if send fails

    # ── CV modes ──────────────────────────────────────────────────────────────

    def _run_lfr(self, frame: np.ndarray) -> tuple[str, np.ndarray]:
        """Line following mode with error handling."""
        try:
            lr = self.line_det.scan(frame)
            cmd = RobotComms.from_lfr(lr.steer)
            display = draw_line_overlay(frame, lr, debug=True)  # Enable debug mode
            return cmd, display
        except Exception as exc:
            log.error("[BRAIN] LFR mode error: %s", exc)
            # Safe fallback
            return "S", frame

    def _run_human(self, frame: np.ndarray) -> tuple[str, np.ndarray]:
        """Human tracking mode with comprehensive error handling."""
        try:
            fh, fw = frame.shape[:2]
            detections = self.human_det.detect(frame)

            if not detections:
                draw_text(
                    frame, "SEARCHING…", (fw // 2 - 80, fh // 2),
                    size=1.0, color=_CLR_YELLOW, thickness=2
                )
                self._state.yolo_info = "no person detected"
                return "R", frame

            try:
                best = max(detections, key=lambda d: d.confidence)
                smooth_bbox = self.ema.update(best.bbox)
                x1, y1, x2, y2 = smooth_bbox

                # Validate bounding box
                if not (0 <= x1 < x2 <= fw and 0 <= y1 < y2 <= fh):
                    raise ValueError(f"Invalid bbox: ({x1}, {y1}, {x2}, {y2})")

                cx = (x1 + x2) // 2

                focal = self._focal_px or compute_focal(fw, HFOV_DEG)
                rotate_deg = pixel_offset_to_angle(cx - fw // 2, focal)
                cmd = RobotComms.from_human_bbox(smooth_bbox, fw, fh, rotate_deg=rotate_deg)

                area_ratio = ((x2 - x1) * (y2 - y1)) / max(fw * fh, 1)  # Prevent division by zero
                draw_detection_box(frame, smooth_bbox, "person", best.confidence, _CLR_GREEN)
                draw_text(
                    frame, f"area={area_ratio:.0%}  rot={rotate_deg:+.1f}°",
                    (x1, min(y2 + 20, fh - 10)), font=cv2.FONT_HERSHEY_PLAIN,
                    size=1.1, color=_CLR_YELLOW
                )

                self._state.yolo_info = (
                    f"person conf={best.confidence:.0%} area={area_ratio:.0%} rot={rotate_deg:+.1f}°"
                )
                return cmd, frame

            except Exception as exc:
                log.warning("[BRAIN] Human tracking calculation error: %s", exc)
                # Fall back to search mode
                self._state.yolo_info = "tracking error - searching"
                return "R", frame

        except Exception as exc:
            log.error("[BRAIN] Human mode error: %s", exc)
            # Safe fallback
            self._state.yolo_info = "mode error"
            return "S", frame

    def _run_vla(self, frame: np.ndarray) -> tuple[str, np.ndarray]:
        """Gemma-powered VLA mode with async inference and change detection."""
        try:
            # 1. Check for significant visual change to trigger new analysis
            if not self._vla_busy and self.vla.has_significant_change(frame):
                self._vla_busy = True
                # Trigger async inference to prevent blocking the main loop
                threading.Thread(
                    target=self._vla_inference_task, 
                    args=(frame.copy(),), 
                    daemon=True
                ).start()

            # 2. Determine command from the latest VLA response
            cmd = "S" # Default stop if no actions
            with self._vla_lock:
                if self._last_vla_resp.get("actions"):
                    # Use the first movement action if available
                    for action in self._last_vla_resp["actions"]:
                        if action.get("type") == "move":
                            cmd = action.get("cmd", "S")
                            break
            
            # 3. HUD status
            status_text = "VLA: Thinking..." if self._vla_busy else "VLA: Waiting for change"
            draw_text(frame, status_text, (10, 60), size=0.6, color=_CLR_BLUE)
            
            return cmd, frame

        except Exception as exc:
            log.error("[BRAIN] VLA mode error: %s", exc)
            draw_text(frame, "VLA ERROR", (10, 60), size=0.6, color=_CLR_RED)
            return "S", frame

    def _vla_inference_task(self, frame: np.ndarray) -> None:
        """Background thread for LLM vision analysis."""
        try:
            resp = self.vla.get_response(frame)
            
            # Update internal state with new JSON response
            with self._vla_lock:
                self._last_vla_resp = resp
            
            # Provide real-time TTS feedback (progress tracking)
            speech = resp.get("speech")
            if speech:
                log.info("[VLA] Speaking: %s", speech)
                # Use pipeline's TTS directly
                if hasattr(self._pipeline, 'tts') and self._pipeline.tts:
                    self._pipeline.tts.speak(speech)
                
        except Exception as exc:
            log.error("[VLA] Inference task failed: %s", exc)
        finally:
            self._vla_busy = False

    # ── HUD overlay ───────────────────────────────────────────────────────────

    def _draw_hud(self, frame: np.ndarray) -> np.ndarray:
        colour = MODE_COLOURS.get(self._state.mode, _CLR_WHITE)
        draw_text(
            frame, f"MODE: {self._state.mode}",
            (10, 32), size=0.9, color=colour, thickness=2
        )
        cmd_label = CMD_NAMES.get(self._state.last_cmd, self._state.last_cmd)
        draw_text(
            frame, f"CMD:  {self._state.last_cmd} ({cmd_label})",
            (10, 64), size=0.7, color=_CLR_WHITE
        )
        phone_ok   = self._state.phone_connected
        sock_ok    = self.use_socket and self.comms.connected
        draw_text(
            frame,
            f"ESP32: {'OK' if sock_ok else '--'}  PHONE: {'OK' if phone_ok else '--'}",
            (10, 90), font=cv2.FONT_HERSHEY_PLAIN, size=1.0,
            color=_CLR_GREEN if sock_ok else _CLR_RED
        )

        # ── PTT Indicator ─────────────────────────────────────────────────────
        if self._state.ptt_active:
            # Use red for high visibility listening state
            draw_text(
                frame, "[ PTT LISTENING ]",
                (frame.shape[1] - 220, 32), size=0.7, color=(0, 0, 255), thickness=2
            )

        return frame

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        # ── Open camera ───────────────────────────────────────────────────
        dev = self.device
        if isinstance(dev, int):
            pass
        elif isinstance(dev, str) and dev.lstrip('-').isdigit():
            dev = int(dev)
        # else, leave as string path
        cap = cv2.VideoCapture(dev)
        if not cap.isOpened():
            sys.exit(
                f"[ERROR] Cannot open camera '{self.device}'.\n"
                "  For phone camera:  scrcpy --video-source=camera --v4l2-sink=/dev/video2 --no-audio --max-fps 30 --max-size=1080\n"
                "  Then run:          python main.py --no-socket --no-web\n"
                "  For laptop webcam: python main.py --laptop --no-socket --no-web"
            )
        log.info("[BRAIN] Camera opened: %s", self.device)

        # Set camera device in state for audio routing decisions
        self._state.camera_device = self.device

        ret, frame = cap.read()
        if not ret:
            sys.exit("[ERROR] Could not read first frame.")
        fh, fw = frame.shape[:2]
        wide_side = fh if fh > fw else fw
        self._focal_px = compute_focal(wide_side, HFOV_DEG)
        log.info("[BRAIN] Frame %dx%d  focal=%.1fpx", fw, fh, self._focal_px)

        # ── ESP32 socket ──────────────────────────────────────────────────
        if self.use_socket:
            self.comms.wait_for_esp32()

        # ── Start web server + voice pipeline ─────────────────────────────
        if self.use_web:
            self._web.start()
            # Register REST API Flask blueprint (inject CommandQueue & RobotState)
            try:
                from backend.api import create_api_blueprint
                timeout_s = 5.0
                waited_s = 0.0
                step_s = 0.1
                while self._web.app is None and waited_s < timeout_s:
                    time.sleep(step_s)
                    waited_s += step_s

                if self._web.app is None:
                    log.warning("[BRAIN] Web app not ready; skipping REST blueprint registration")
                else:
                    self._web.app.register_blueprint(create_api_blueprint(
                        command_queue=getattr(self._pipeline, 'cmd_queue', None),
                        robot_state=self._state
                    ))
            except Exception as api_exc:
                log.warning(f"[BRAIN] Failed to register REST API blueprint: {api_exc}")
        self._pipeline.start()

        print("\n[BRAIN] Running.  Hotkeys: q=quit  1=LFR  2=Human  3=VLA  0=Idle")
        if not self.use_wake_word:
            print("[BRAIN] PTT mode: hold SPACE in the Robot Brain window to talk.")
        print()
        self._state.mode = MODE_IDLE

        # Error tracking for recovery
        consecutive_errors = 0
        max_consecutive_errors = 10
        last_good_frame = None

        try:
            while True:
                try:
                    ret, frame = cap.read()
                    if not ret:
                        log.warning("[BRAIN] Frame read failed – retrying…")
                        consecutive_errors += 1
                        if consecutive_errors > max_consecutive_errors:
                            log.error("[BRAIN] Too many consecutive frame read failures")
                            break
                        time.sleep(0.1)
                        continue

                    # Reset error counter on successful frame read
                    consecutive_errors = 0
                    last_good_frame = frame

                    # Validate frame
                    if frame is None or frame.size == 0:
                        log.warning("[BRAIN] Invalid frame received")
                        continue

                    cmd = "S"  # Safe default

                    # ── CV dispatch ───────────────────────────────────────────────
                    try:
                        match self._state.mode:
                            case RobotMode.LFR.value:
                                cmd, display = self._run_lfr(frame)
                            case RobotMode.HUMAN_TRACK.value:
                                cmd, display = self._run_human(frame)
                            case RobotMode.VLA.value:
                                cmd, display = self._run_vla(frame)
                            case RobotMode.IDLE.value:
                                cmd = "S"
                                display = frame
                            case RobotMode.MANUAL.value:
                                cmd = self._state.last_cmd
                                display = frame
                            case unknown_mode:
                                log.warning("[BRAIN] Unknown mode: %s", unknown_mode)
                                cmd = "S"
                                display = frame

                    except Exception as exc:
                        log.error("[BRAIN] CV processing error: %s", exc)
                        # Use safe fallback
                        cmd = "S"
                        display = frame
                        # Draw error message
                        try:
                            draw_text(
                                display, "CV ERROR - STOPPED",
                                (10, frame.shape[0] - 30), size=0.7, color=_CLR_RED
                            )
                        except Exception:
                            # Even drawing failed, use last good frame if available
                            display = last_good_frame if last_good_frame is not None else frame

                    # ── Send ESP32 command ────────────────────────────────────────
                    self._send(cmd)

                    # ── Push frame to web dashboard (needs copy for encoding) ─────
                    if self.use_web:
                        try:
                            if display is frame:
                                display_frame = self._get_pooled_frame_copy(display)
                            else:
                                display_frame = display
                            self._web.push_frame(display_frame)
                        except Exception as exc:
                            log.warning("[BRAIN] Web frame push failed: %s", exc)
                            # Continue without web update

                    # ── HUD + display (create copy for drawing if needed) ─────────
                    hud_frame = None
                    try:
                        if display is frame:
                            hud_frame = self._get_pooled_frame_copy(frame)
                            display = hud_frame
                        display = self._draw_hud(display)
                        
                        try:
                            cv2.imshow("Robot Brain", display)
                        except Exception:
                            # Fallback to pygame if cv2.imshow fails (e.g. no GUI backend)
                            from pygame_preview import pygame_bgr_preview
                            pygame_bgr_preview(display, window_name="Robot Brain (Pygame Fallback)")

                    except Exception as exc:
                        log.warning("[BRAIN] Display update failed: %s", exc)
                        # Continue without display update
                    finally:
                        # Return frame to pool for reuse
                        if hud_frame is not None and hud_frame is not frame:
                            self._return_frame_to_pool(hud_frame)

                    # ── Keyboard shortcuts ────────────────────────────────────────
                    try:
                        key = cv2.waitKey(1) & 0xFF
                        # Universal PTT: Allow space bar force-listen even if wake-word is technically enabled
                        self._state.ptt_active = (key == ord(" "))
                        if self._state.ptt_active:
                            self._pipeline.trigger_force_listen()

                        if key == ord("q"):
                            print("[BRAIN] Quit.")
                            break
                        elif key == ord("1"):
                            self._state.mode = MODE_LFR
                        elif key == ord("2"):
                            self._state.mode = MODE_HUMAN
                        elif key == ord("3"):
                            self._state.mode = MODE_VLA
                        elif key == ord("4"):
                            self._state.mode = MODE_MANUAL
                        elif key == ord("0"):
                            self._state.mode = MODE_IDLE
                            self._send("S")
                    except Exception as exc:
                        log.warning("[BRAIN] Keyboard handling failed: %s", exc)
                        # Continue without keyboard input

                    time.sleep(LOOP_SLEEP_S)

                except KeyboardInterrupt:
                    print("\n[BRAIN] Interrupted by user.")
                    break
                except Exception as exc:
                    log.error("[BRAIN] Unexpected error in main loop: %s", exc)
                    consecutive_errors += 1
                    if consecutive_errors > max_consecutive_errors:
                        log.error("[BRAIN] Too many consecutive errors, shutting down")
                        break
                    time.sleep(0.5)  # Longer delay after unexpected error

        except Exception as exc:
            log.error("[BRAIN] Fatal error: %s", exc)

        finally:
            # ── Cleanup ───────────────────────────────────────────────────────
            try:
                self._send("S")  # Emergency stop
                self._state.ptt_active = False
                cap.release()
                if self.use_socket:
                    self.comms.close()
                if self.use_web:
                    self._web.stop()
                cv2.destroyAllWindows()
                log.info("[BRAIN] Shutdown complete.")
            except Exception as exc:
                log.error("[BRAIN] Cleanup error: %s", exc)


# ─────────────────────────── entry point ─────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="JARVIS Robot Brain")
    p.add_argument("--device", default="laptop",
                   help="Camera device alias (laptop/mobile/phone) or device path/index (default: laptop)")
    p.add_argument("--host", default="0.0.0.0",
                   help="ESP32 TCP server bind address")
    p.add_argument("--port", type=int, default=9999,
                   help="ESP32 TCP port (default: 9999)")
    p.add_argument("--web-port", type=int, default=5000,
                   help="Flask-SocketIO HTTP/WS port (default: 5000)")
    p.add_argument("--no-socket", action="store_true",
                   help="Disable ESP32 socket (CV+voice only, no motors)")
    p.add_argument("--no-web", action="store_true",
                   help="Disable Flask web server (CV+voice only, no dashboard)")
    p.add_argument("--laptop", action="store_true",
                   help="Use laptop webcam (device 1) instead of /dev/video2")
    p.add_argument("--model", default="gemma4-e2b-nothink:latest",
                   help="Ollama model for VLA mode (default: gemma4-e2b-nothink:latest)")
    p.add_argument("--sensitivity", type=float, default=0.6,
                   help="Wake word sensitivity (0.0 to 1.0, default: 0.6)")
    p.add_argument("--stt-threshold", type=int, default=850,
                   help="Speech energy threshold (default: 850)")
    p.add_argument("--no-wake-word", action="store_true",
                   help="Disable wake-word and use hold-SPACE push-to-talk in OpenCV window")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    from backend.config.config import CAMERA_ALIAS_RESOLVE  # added for device aliasing

    device_arg = args.device
    device_real = CAMERA_ALIAS_RESOLVE.get(device_arg, device_arg)

    brain = RobotBrain(
        device="1" if args.laptop else device_real,
        esp_host=args.host,
        esp_port=args.port,
        web_port=args.web_port,
        use_socket=not args.no_socket,
        use_web=not args.no_web,
        vla_model=args.model,
        wake_sens=args.sensitivity,
        stt_threshold=args.stt_threshold,
        use_wake_word=not args.no_wake_word,
    )
    brain.run()


if __name__ == "__main__":
    main()
