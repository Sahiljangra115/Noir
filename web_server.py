"""
web_server.py
──────────────
Flask-SocketIO server that runs as a background thread alongside the robot.

Responsibilities
────────────────
1. Serve the legacy browser dashboard at  http://<laptop-ip>:5000
2. Accept a WebSocket connection from the Flutter phone app (SocketIO)
3. Forward phone mic PCM16 audio to the VoicePipeline's audio queue
4. Receive sensor data (IMU + GPS) from the phone → RobotState
5. Signal force-listen on arc reactor tap
6. Push TTS WAV bytes to the phone speaker (emitted by PiperTTS callback)
7. Broadcast RobotState snapshots every 300 ms to the phone UI

SocketIO events
───────────────
  Phone → Laptop
    audio_data   binary   PCM16 LE, 16 kHz mono, 512-sample (1024-byte) chunks
    sensor_data  JSON     {imu:{accel:{x,y,z},gyro:{x,y,z}}, gps:{lat,lon,alt,speed}}
    force_listen (empty)  arc reactor tap → skip the wake word for one cycle

  Laptop → Phone
    tts_audio    binary   raw WAV bytes (Piper output) — phone plays on speaker
    state_update JSON     {mode, last_cmd, goto_target, yolo_info,
                           phone_connected, imu, gps,
                           last_heard, jarvis_response}

Usage (wired in main.py):
    state    = RobotState()
    web      = WebServer(state=state, comms=robot_comms)
    pipeline = VoicePipeline(comms=robot_comms, state=state)
    web.set_voice_pipeline(pipeline)   # registers TTS callback
    web.start()
    pipeline.start()
"""
import json
import logging
import queue
import threading
import time
import os
import hmac
from typing import Optional
from functools import wraps

import cv2
import numpy as np
from dotenv import load_dotenv

from backend.config import config

# Load environment variables from .env
load_dotenv()

log = logging.getLogger(__name__)

# Interval of the state_update broadcast to the phone. Documented in the module
# header, the README and CLAUDE.md — keep all four in step if it changes.
STATE_PUSH_INTERVAL_S = 0.3

# MJPEG stream frame rate for GET /frame.
FRAME_STREAM_FPS = 15

# Modes the CV loop in backend/main.py dispatches on. Anything outside this set
# would leave RobotBrain logging "Unknown mode" and holding the motors stopped.
VALID_MODES = frozenset({"LFR", "HUMAN_TRACK", "VLA", "MANUAL", "IDLE"})

# ── Lazy imports ──────────────────────────────────────────────────────────────
_flask_ok = False
try:
    from flask import Flask, Response, jsonify, render_template_string, request, abort
    from flask_socketio import SocketIO, emit, disconnect
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _flask_ok = True
except ImportError:
    pass

def _token_matches(presented, expected: str) -> bool:
    """Constant-time token compare that tolerates hostile input.

    ``hmac.compare_digest`` raises TypeError on non-ASCII ``str`` operands, so a
    token with one accented character would surface as a 500 instead of a 401.
    Comparing UTF-8 bytes keeps the timing property and answers every input.
    """
    if not isinstance(presented, str):
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        expected = os.getenv('JARVIS_SECRET_KEY')
        if not expected:
            log.error("[WEB] JARVIS_SECRET_KEY is not configured")
            return jsonify({"status": "error", "msg": "Server auth misconfigured"}), 503
        if not token:
            log.debug("[WEB] Missing auth header from %s", request.remote_addr)
            return jsonify({"status": "error", "msg": "Unauthorized"}), 401
        if not _token_matches(token, f"Bearer {expected}"):
            log.warning("[WEB] Unauthorized REST access attempt from %s", request.remote_addr)
            return jsonify({"status": "error", "msg": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

class WebServer:
    """
    Flask-SocketIO server in a daemon thread.
    Bridges the Flutter phone app <-> VoicePipeline <-> RobotState.
    """

    def __init__(
        self,
        state,
        comms,
        host: str = "0.0.0.0",
        port: int = 5000,
    ) -> None:
        self._state  = state
        self._comms  = comms
        self._host   = host
        self._port   = port

        # Phone audio chunks land here; VoicePipeline reads from it
        self._audio_queue: queue.Queue = queue.Queue(maxsize=400)

        self._voice_pipeline = None

        # Frame buffer for optional MJPEG dashboard (browser only)
        self._frame_lock  = threading.Lock()
        self._frame_bytes: Optional[bytes] = None
        self._has_clients = False  # True while at least one /frame viewer is live
        self._stream_clients = 0
        self._stream_lock = threading.Lock()

        self._sio: Optional[object] = None

        # Shared timer for move commands to avoid thread leaks
        self._move_timer: Optional[threading.Timer] = None
        self._move_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._serve_started = threading.Event()
        self.app: Optional[object] = None
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    def set_voice_pipeline(self, vp) -> None:
        """Wire VoicePipeline in. Registers the TTS wav_callback."""
        self._voice_pipeline = vp
        vp.tts.set_wav_callback(self._send_tts_audio)
        log.info("[WEB] VoicePipeline registered, TTS callback set.")

    def push_frame(self, frame: np.ndarray) -> None:
        """Call every CV loop iteration — keeps MJPEG browser dashboard live."""
        # Input validation
        if frame is None or frame.size == 0:
            return

        if not isinstance(frame, np.ndarray) or len(frame.shape) != 3:
            return

        # Only encode frames if we have browser clients connected
        if not self._has_clients:
            return

        try:
            success, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not success:
                log.warning("[WEB] Frame encoding failed")
                return

            with self._frame_lock:
                self._frame_bytes = buf.tobytes()

        except Exception as exc:
            log.error("[WEB] Frame processing error: %s", exc)
            # Continue without updating frame

    def update_conversation(self, heard: str, response: str) -> None:
        """Kept for compatibility — conversation state now lives in RobotState."""
        pass

    def start(self) -> None:
        if not _flask_ok:
            log.warning(
                "[WEB] flask-socketio not installed — server disabled.\n"
                "      uv pip install flask-socketio simple-websocket"
            )
            return
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True, name="web-server")
        self._thread.start()
        log.info("[WEB] SocketIO server starting at http://%s:%d", self._host, self._port)

    def stop(self) -> None:
        """Best-effort stop for tests and standalone runs."""
        self._running = False
        with self._move_lock:
            if self._move_timer is not None:
                self._move_timer.cancel()
                self._move_timer = None

    def _handle_command_payload(self, data: dict) -> tuple[dict, int]:
        """Shared command handler for REST and SocketIO command events."""
        typ = data.get("type", "")

        if typ == "mode":
            value = data.get("value", data.get("mode", "IDLE"))
            if value in VALID_MODES:
                self._state.mode = value
                log.info("[WEB] Mode set to %s", value)
                return {"status": "ok", "mode": value}, 200
            return {"status": "error", "msg": "unknown mode"}, 400

        if typ == "move":
            cmd_char_raw = str(data.get("cmd", "S")).upper().strip()
            cmd_char = cmd_char_raw[:1] if cmd_char_raw else ""
            try:
                duration = float(data.get("duration", 1.0))
            except (TypeError, ValueError):
                return {"status": "error", "msg": "invalid duration"}, 400

            duration = max(0.1, min(duration, config.MOVE_MAX_DURATION_S))

            if cmd_char and cmd_char in "FBLRS":
                # A manual command only survives if the CV loop stops competing
                # for the motors. In LFR/HUMAN_TRACK/VLA it recomputes a command
                # every frame, and in IDLE it re-sends "S" — either way the
                # driver pad was overridden ~50 ms after the tap. MANUAL makes
                # the loop replay state.last_cmd instead, so the command holds.
                # "S" additionally means stop, so it drops straight to IDLE.
                if cmd_char == "S":
                    self._state.mode = "IDLE"
                else:
                    self._state.mode = "MANUAL"
                self._state.last_cmd = cmd_char
                self._comms.send(cmd_char)

                with self._move_lock:
                    if self._move_timer is not None:
                        self._move_timer.cancel()

                    def _stop():
                        self._comms.send("S")
                        self._state.last_cmd = "S"
                        # Only stand down if this timer's move is still the one
                        # in charge; a newer command may have taken over.
                        if self._state.mode == "MANUAL":
                            self._state.mode = "IDLE"

                    self._move_timer = threading.Timer(duration, _stop)
                    self._move_timer.daemon = True
                    self._move_timer.start()

                return {"status": "ok", "cmd": cmd_char}, 200
            return {"status": "error", "msg": "unknown cmd"}, 400

        return {"status": "error", "msg": "unknown type"}, 400

    # ── TTS relay (called from PiperTTS thread) ───────────────────────────────

    def _send_tts_audio(self, wav_bytes: bytes) -> None:
        """Emit WAV bytes to phone speaker. Called instead of aplay when phone connected."""
        if self._sio is not None:
            try:
                self._sio.emit("tts_audio", wav_bytes)
            except Exception as exc:
                log.debug("[WEB] tts_audio emit error: %s", exc)

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def _full_snapshot(self) -> dict:
        """RobotState.snapshot() now includes last_heard + jarvis_response."""
        return self._state.snapshot()

    # ── Background state broadcast ───────────────────────────────────────────

    def _state_pusher(self) -> None:
        while self._running:
            time.sleep(STATE_PUSH_INTERVAL_S)
            if self._sio is not None and self._state.phone_connected:
                try:
                    self._sio.emit("state_update", self._full_snapshot())
                except Exception as exc:
                    log.debug("[WEB] state_update emit error: %s", exc)

    def state_pusher_factory(self) -> threading.Thread:
        """Return a fresh non-daemon Thread running the periodic state push.

        For ThreadSupervisor registration. Must only be called after
        ``start()`` has been called and the server has begun serving.
        """
        return threading.Thread(
            target=self._state_pusher, daemon=False, name="state-pusher"
        )

    # ── Flask + SocketIO main ─────────────────────────────────────────────────

    def _serve(self) -> None:
        import logging as _logging
        _logging.getLogger("werkzeug").setLevel(_logging.ERROR)

        secret = os.getenv("JARVIS_SECRET_KEY")
        if not secret:
            log.error("[WEB] JARVIS_SECRET_KEY is not set; refusing to start web server")
            self._running = False
            return

        app = Flask(__name__)
        app.config["SECRET_KEY"] = secret
        # Published only once the server is actually going to serve, so
        # RobotBrain does not register its REST blueprint on a dead app.
        self.app = app

        # Rate limiting to prevent command spamming
        limiter = Limiter(
            get_remote_address,
            app=app,
            default_limits=["10000 per hour"],
            storage_uri="memory://",
        )

        from backend.config.config import ALLOWED_ORIGINS

        @app.after_request
        def add_cors_headers(response):
            origin = request.headers.get("Origin")
            if origin and origin in ALLOWED_ORIGINS:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
                response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            return response

        sio = SocketIO(
            app,
            async_mode="threading",
            cors_allowed_origins=ALLOWED_ORIGINS,
            binary=True,
            logger=False,
            engineio_logger=False,
        )
        self._sio = sio

        # ── HTTP routes ───────────────────────────────────────────────────────

        @app.route("/")
        def index():
            # The dashboard shows telemetry only; it cannot embed /frame because
            # an <img> tag cannot send the Bearer header. So it is not a frame
            # consumer and must not switch JPEG encoding on in the CV loop.
            return render_template_string(_HTML)

        @app.route("/status")
        @limiter.exempt
        @require_auth
        def status():
            return jsonify(self._full_snapshot())

        @app.route("/command", methods=["POST"])
        @require_auth
        @limiter.limit("5 per second")
        def command():
            cl = request.content_length
            if cl is not None and cl > 1_000_000:
                return jsonify({"status": "error", "msg": "payload too large"}), 413
            data     = request.get_json(silent=True) or {}
            body, status = self._handle_command_payload(data)
            return jsonify(body), status

        @app.route("/frame")
        @require_auth
        def frame_stream():
            """MJPEG stream consumed by the Flutter MjpegStream widget."""

            def _generate():
                # Encoding in push_frame is gated on there being a viewer, so
                # the count has to come back down when the last one leaves.
                with self._stream_lock:
                    self._stream_clients += 1
                    self._has_clients = True
                try:
                    # Bound by _running so shutdown does not leave one generator
                    # thread per client spinning forever.
                    while self._running:
                        with self._frame_lock:
                            jpg = self._frame_bytes
                        if jpg:
                            yield (
                                b"--frame\r\n"
                                b"Content-Type: image/jpeg\r\n"
                                b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
                                + jpg + b"\r\n"
                            )
                        time.sleep(1 / FRAME_STREAM_FPS)
                finally:
                    with self._stream_lock:
                        self._stream_clients = max(0, self._stream_clients - 1)
                        self._has_clients = self._stream_clients > 0

            return Response(
                _generate(),
                mimetype="multipart/x-mixed-replace; boundary=frame",
            )

        # ── SocketIO events ───────────────────────────────────────────────────

        @sio.on("connect")
        def on_connect(auth=None):
            expected = os.getenv('JARVIS_SECRET_KEY')
            if not expected:
                log.error("[WEB] JARVIS_SECRET_KEY is not configured")
                return False
            
            # Support both 'auth' dict (SocketIO 4+) and 'token' query param
            token = None
            if auth and isinstance(auth, dict):
                token = auth.get("token")
            if not token:
                token = request.args.get("token")

            if not token or not _token_matches(token, expected):
                log.warning("[WEB] Unauthorized SocketIO connection attempt from %s", request.remote_addr)
                return False  # Refuse connection

            log.info("[WEB] Phone connected: %s", request.sid)
            self._state.phone_connected = True
            if self._voice_pipeline is not None:
                self._voice_pipeline.set_audio_queue(self._audio_queue)
            emit("state_update", self._full_snapshot())

        @sio.on("disconnect")
        def on_disconnect():
            log.info("[WEB] Phone disconnected: %s", request.sid)
            self._state.phone_connected = False
            if self._voice_pipeline is not None:
                self._voice_pipeline.clear_audio_queue()
            # Drain stale audio so next session starts clean
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break

        @sio.on("audio_data")
        def on_audio_data(data):
            """
            Binary PCM16 LE, 16 kHz, mono.
            512 samples per chunk = 1024 bytes = 32 ms of audio.
            Drop oldest if queue is full to avoid growing latency.
            """
            if not isinstance(data, (bytes, bytearray)) or len(data) > config.MAX_AUDIO_PAYLOAD_BYTES:
                emit("audio_error", {"reason": "oversize_or_wrong_type"})
                return
            raw = bytes(data)
            if self._audio_queue.full():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                self._audio_queue.put_nowait(raw)
            except queue.Full:
                pass

        @sio.on("sensor_data")
        def on_sensor_data(data):
            """
            JSON dict: {
              imu: {accel: {x,y,z}, gyro: {x,y,z}},
              gps: {lat, lon, alt, speed}
            }
            """
            if not isinstance(data, dict):
                emit("sensor_error", {"reason": "wrong_type"})
                return
            try:
                payload_len = len(json.dumps(data, default=str))
            except (TypeError, ValueError):
                emit("sensor_error", {"reason": "unserializable"})
                return
            if payload_len > config.MAX_SENSOR_PAYLOAD_BYTES:
                emit("sensor_error", {"reason": "oversize"})
                return
            if "imu" in data:
                self._state.imu = data["imu"]
            if "gps" in data:
                self._state.gps = data["gps"]

        @sio.on("force_listen")
        def on_force_listen(data=None):
            """Arc reactor tap — skip the wake word for one cycle."""
            log.info("[WEB] force_listen received.")
            if self._voice_pipeline is not None:
                self._voice_pipeline.trigger_force_listen()

        @sio.on("command")
        def on_command(data):
            """Optional direct command channel for mobile clients."""
            if not isinstance(data, dict):
                emit("command_ack", {"status": "error", "msg": "invalid payload"})
                return
            body, status = self._handle_command_payload(data)
            body["http_status"] = status
            emit("command_ack", body)

        # ── State pusher thread is managed by ThreadSupervisor in main.py ──
        # (see backend/main.py — supervisor.register("state-pusher", web.state_pusher_factory))

        # ── Run server (blocks this daemon thread) ─────────────────────────
        sio.run(
            app,
            host=self._host,
            port=self._port,
            allow_unsafe_werkzeug=True,
        )

# ── Embedded dashboard HTML ───────────────────────────────────────────────────
_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>JARVIS Robot Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #0d0d0d; color: #e0e0e0; font-family: monospace;
           display: flex; flex-direction: column; align-items: center;
           padding: 20px; gap: 16px; }
    h1   { color: #00e5ff; letter-spacing: 4px; font-size: 1.4rem; }
    #status { background: #1a1a1a; padding: 12px 16px; border-radius: 6px;
              width: 100%; max-width: 640px; line-height: 1.8; font-size: 0.9rem;}
    .label  { color: #888; }
    .val    { color: #00e5ff; font-weight: bold; }
    #controls { display: grid; grid-template-columns: repeat(3, 80px); gap: 8px; }
    #controls button {
      padding: 14px 0; font-size: 1.2rem; border: none; border-radius: 6px;
      cursor: pointer; background: #1e1e1e; color: #fff; transition: background 0.15s;
    }
    #controls button:active { background: #00e5ff; color: #000; }
    #mode-btns { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
    #mode-btns button {
      padding: 8px 14px; font-size: 0.8rem; border: 1px solid #444;
      border-radius: 20px; cursor: pointer; background: #1e1e1e; color: #ccc;
    }
    #mode-btns button:hover { border-color: #00e5ff; color: #00e5ff; }
    #log { background:#111; border:1px solid #333; padding:8px; border-radius:6px;
           width:100%; max-width:640px; height:120px; overflow-y:auto;
           font-size:0.75rem; color:#888; }
    #phone-badge { padding:4px 10px; border-radius:12px; font-size:0.75rem;
                   background:#1a1a1a; }
    .connected    { color:#00ff88; border:1px solid #00ff88; }
    .disconnected { color:#ff4444; border:1px solid #ff4444; }
  </style>
</head>
<body>
  <h1>&#9679; JARVIS</h1>
  <span id="phone-badge" class="disconnected">PHONE: OFFLINE</span>

  <div id="status">
    <span class="label">MODE </span><span class="val" id="s-mode">–</span> &nbsp;
    <span class="label">CMD </span><span class="val" id="s-cmd">–</span><br>
    <span class="label">CAMERA </span><span id="s-yolo" style="color:#aaa">–</span><br>
    <span class="label">LAST HEARD </span><span id="s-heard" style="color:#aaa">–</span><br>
    <span class="label">JARVIS </span><span id="s-response" style="color:#00e5ff">–</span>
  </div>

  <div id="controls">
    <div></div>
    <button onclick="cmd('F')" title="Forward">&#9650;</button>
    <div></div>
    <button onclick="cmd('L')" title="Left">&#9668;</button>
    <button onclick="cmd('S')" title="Stop">&#9632;</button>
    <button onclick="cmd('R')" title="Right">&#9658;</button>
    <div></div>
    <button onclick="cmd('B')" title="Backward">&#9660;</button>
    <div></div>
  </div>

  <div id="mode-btns">
    <button onclick="mode('LFR')">Line Follow</button>
    <button onclick="mode('HUMAN_TRACK')">Track Human</button>
    <button onclick="mode('VLA')">Autonomous</button>
    <button onclick="mode('IDLE')">IDLE / Stop</button>
  </div>

  <div id="log"></div>

<script>
  const token = localStorage.getItem('jarvisToken') || '';

  function authHeaders(extra = {}) {
    const headers = {...extra};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return headers;
  }

  function addLog(msg) {
    const el = document.getElementById('log');
    el.innerHTML += new Date().toLocaleTimeString() + '  ' + msg + '<br>';
    el.scrollTop = el.scrollHeight;
  }
  function cmd(c) {
    fetch('/command', {method:'POST',
      headers:authHeaders({'Content-Type':'application/json'}),
      body: JSON.stringify({type:'move', cmd:c, duration:1.0})
    }).then(r=>r.json()).then(d=>addLog('move ' + c + ' \u2192 ' + d.status));
  }
  function mode(m) {
    fetch('/command', {method:'POST',
      headers:authHeaders({'Content-Type':'application/json'}),
      body: JSON.stringify({type:'mode', value:m})
    }).then(r=>r.json()).then(d=>addLog('mode ' + m + ' \u2192 ' + d.status));
  }
  setInterval(() => {
    fetch('/status', {headers:authHeaders()}).then(r=>r.json()).then(d=>{
      if (d.status === 'error') {
        addLog('status error: ' + d.msg);
        return;
      }
      document.getElementById('s-mode').textContent     = d.mode;
      document.getElementById('s-cmd').textContent      = d.last_cmd;
      document.getElementById('s-yolo').textContent     = d.yolo_info;
      document.getElementById('s-heard').textContent    = d.last_heard      || '\u2013';
      document.getElementById('s-response').textContent = d.jarvis_response || '\u2013';
      const badge = document.getElementById('phone-badge');
      if (d.phone_connected) {
        badge.textContent = 'PHONE: ONLINE';
        badge.className = 'connected';
      } else {
        badge.textContent = 'PHONE: OFFLINE';
        badge.className = 'disconnected';
      }
    }).catch(() => {});
  }, 1000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    # For quick standalone testing (mocking dependencies)
    from backend.services.robot_state import RobotState
    from backend.esp32.robot_comms import RobotComms
    
    s = RobotState()
    c = RobotComms(host="127.0.0.1", port=8888) # mock
    ws = WebServer(state=s, comms=c)
    ws.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        ws.stop()
