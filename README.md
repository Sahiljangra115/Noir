<div align="center">

# NOIR

**An autonomous robot assistant combining computer vision, a local voice pipeline, and on-device language reasoning.**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flutter](https://img.shields.io/badge/Flutter-Material%203-02569B?logo=flutter&logoColor=white)](https://flutter.dev/)
[![ESP-IDF](https://img.shields.io/badge/ESP--IDF-v6-E7352C?logo=espressif&logoColor=white)](https://docs.espressif.com/)
[![Status](https://img.shields.io/badge/status-v0.4.0-success)]()

</div>

---

## Overview

NOIR is a final year engineering project: a mobile robot that listens, sees, and acts on its own. It runs three independent pipelines at once. A voice pipeline turns a spoken wake word into a parsed command. A vision pipeline tracks people and follows lines from a live camera feed. A web bridge streams state to a Flutter app and accepts manual control.

The Python backend does the reasoning. An ESP32 drives the motors over Wi-Fi. A Flutter app gives you telemetry, manual control, and the camera stream from a phone.

All language model output is validated before any motor moves, and every network endpoint requires a token. See [Security](#security) for the details.

---

## Features

- **Voice pipeline.** Porcupine wake word, Faster-Whisper speech-to-text on CUDA, Gemma 4 reasoning through Ollama, and Piper text-to-speech.
- **Vision and navigation.** YOLOv8 person tracking, a hybrid ML and OpenCV line follower, and a vision-language-action mode built on Gemma 4 vision.
- **Mobile control.** A Flutter app with live telemetry, manual drive controls, and an MJPEG camera view.
- **Resilient runtime.** A thread supervisor restarts crashed workers, the ESP32 link auto-reconnects, and a health check reports system state.
- **Validated commands.** Model output is checked against a Pydantic schema and an allow-list before it ever reaches the hardware.

---

## System Architecture

Three concurrent loops share a single thread-safe `RobotState`.

```
                         +------------------------+
   camera frame  ----->  |  CV Loop (RobotBrain)  | ----> motor command --+
                         |  mode dispatch          |                       |
                         +------------------------+                        v
                                                                  +-----------------+
   wake word -> STT -> LLM -> TTS  (Voice Pipeline) ------------> |   RobotComms    |
                                                                  |  TCP : 9999     | --> ESP32 motors
   Flutter app <--- state every 300ms ---  Web Bridge  <--------> +-----------------+
                  ---> control commands --- Flask-SocketIO : 5000
```

- **CV loop** (`backend/main.py`, `RobotBrain`): reads a frame, dispatches on `RobotMode`, emits a motor command, sends it through `RobotComms`.
- **Voice pipeline** (`backend/services/voice_pipeline.py`): wake word, transcription, model call, speech output.
- **Web bridge** (`web_server.py`): Flask-SocketIO on port 5000, pushes `RobotState` snapshots every 300 ms, receives control commands.

---

## Tech Stack

| Layer      | Technology                                            |
| ---------- | ----------------------------------------------------- |
| Backend    | Python 3.12+, Flask-SocketIO, OpenCV, YOLOv8n         |
| Voice      | Porcupine, Faster-Whisper (CUDA), Piper TTS           |
| Language   | Gemma 4 (`gemma4-e2b-nothink`) via Ollama             |
| Vision ML  | MobileNetV2 (fine-tuned), PyTorch                     |
| Mobile     | Flutter, socket_io_client, Provider, Material 3       |
| Hardware   | ESP32 (ESP-IDF v6), L298N H-bridge, TCP port 9999     |

---

## Repository Layout

```
backend/
  main.py                      RobotBrain orchestrator (CV loop + mode dispatch)
  services/
    voice_pipeline.py          full voice loop
    robot_state.py             shared thread-safe state (RLock + deepcopy)
    command_queue.py           async motor command queue
    supervisor.py              thread supervisor / auto-restart
    health.py                  system health checks
  esp32/robot_comms.py         TCP client to the ESP32
  config/config.py             typed env config, validated on startup
web_server.py                  WebServer class, SocketIO handlers, auth
tracker.py                     HumanDetector, HybridLineFollower
vision_processor.py            Gemma vision-language processor
jarvis_app/                    Flutter app (screens + glass widgets)
tests/                         unit / integration / e2e suites
```

---

## Getting Started

### 1. Backend

The project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
uv sync                       # create the venv and install from uv.lock
```

### 2. Configuration

Create a `.env` file in the project root. It is git-ignored and must never be committed.

```env
JARVIS_SECRET_KEY=your_secure_token
PORCUPINE_ACCESS_KEY=your_picovoice_access_key
```

The config layer validates these on startup. A missing secret key returns `503` rather than running unprotected.

### 3. Run the backend

```bash
uv run python -m backend.main

# laptop / no-hardware development mode:
uv run python -m backend.main --no-socket --no-web --laptop
```

NOIR then listens for the wake word "Noir". Use `--no-wake-word` for push-to-talk during development.

### 4. Mobile app

```bash
cd jarvis_app
flutter pub get
flutter build apk --debug
# output: jarvis_app/build/app/outputs/flutter-apk/app-debug.apk
```

### 5. ESP32 firmware

Flash the controller in `backend/esp32` with ESP-IDF v6:

```bash
cd backend/esp32
idf.py set-target esp32
idf.py flash monitor
```

The board joins your Wi-Fi and listens for single-character commands (`F B L R S`) on TCP port 9999.

---

## Security

- Secrets live in `.env` and are never committed or hard-coded.
- REST requests authenticate with `Authorization: Bearer <token>`, compared using `hmac.compare_digest`. A missing server key returns `503` instead of bypassing the check.
- SocketIO connections require a `token` at handshake time, through the query string or the auth dictionary.
- Language model output passes through a Pydantic `LLMResponse` before execution. Commands are allow-listed to `{F, B, L, R, S}` with a duration in `[0.1, 30.0]` seconds.
- `RobotState` is guarded by an `RLock` and returns deep copies, so callers never hold a mutable reference to shared state.

---

## Testing

```bash
uv run pytest                 # full suite
uv run pytest --cov           # with coverage
```

The suite covers resilience, unit, integration, and end-to-end paths.

---

## Roadmap

- **Near term:** sharpen object recognition and finish the remaining app screens.
- **Mid term:** multi-robot coordination and a cloud language model fallback.
- **Long term:** swarm behavior across several units.

---

<div align="center">
<sub>Final year engineering project. Built and maintained by Sahil.</sub>
</div>
