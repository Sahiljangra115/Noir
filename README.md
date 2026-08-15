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

- **Voice pipeline.** openWakeWord wake word, Faster-Whisper speech-to-text, Gemma 4 reasoning through Ollama, and Piper text-to-speech. Wake word works on the laptop mic or on phone audio streamed over the socket; a spacebar or in-app tap acts as push-to-talk.
- **Vision and navigation.** YOLOv8 person tracking, a line follower that prefers a fine-tuned MobileNetV2 classifier and falls back to an OpenCV scanner when the weights are absent, and a vision-language-action mode built on Gemma 4 vision.
- **Mobile control.** A Flutter app with live telemetry, manual drive controls, an MJPEG camera view, and playback of the robot's speech through the phone speaker.
- **Resilient runtime.** A thread supervisor restarts crashed workers, the ESP32 link auto-reconnects, a firmware failsafe cuts the motors if the brain goes quiet, and a health check reports system state.
- **Validated commands.** Model output and REST input are both checked against the same Pydantic schema and a socket-level allow-list before anything reaches the hardware.

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
   Flutter app <--- state every 300 ms ---  Web Bridge  <-------> +-----------------+
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
| Voice      | openWakeWord, Faster-Whisper (CUDA), Piper TTS        |
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
# Required. Shared by the REST Bearer header and the SocketIO handshake.
JARVIS_SECRET_KEY=your_secure_token

# Voice. Set JARVIS_VOICE=0 to skip Piper validation entirely.
JARVIS_PIPER_BIN=/path/to/piper
JARVIS_PIPER_MODEL=/path/to/en_US-amy-medium.onnx
JARVIS_PIPER_CONFIG=/path/to/en_US-amy-medium.onnx.json

# Optional, shown with their defaults.
JARVIS_WAKE_KEYWORD=hey_jarvis      # hey_jarvis | alexa | hey_mycroft
JARVIS_WAKE_SENSITIVITY=0.5
JARVIS_WHISPER_MODEL=small.en
JARVIS_WHISPER_DEVICE=auto          # auto falls back to CPU without CUDA
JARVIS_OLLAMA_MODEL=gemma4-e2b-nothink:latest
JARVIS_OLLAMA_TIMEOUT_S=30          # a cold model load costs 20-40 s
JARVIS_MOVE_MAX_DURATION_S=5        # ceiling on any single timed move
JARVIS_LINE_MODEL=~/Developer/Model_finetune/line_classifier.pth
```

`config.validate_config()` runs at startup and raises before any thread spawns,
so a bad value fails fast instead of surfacing deep inside a service. A missing
secret key makes the web server refuse to start and every REST route answer
`503` rather than running unprotected.

### 3. Run the backend

```bash
uv run python -m backend.main

# laptop / no-hardware development mode:
uv run python -m backend.main --no-socket --no-web --laptop
```

NOIR then listens for the wake word. openWakeWord ships a fixed set of stock
models, so the phrase is one of **"Hey Jarvis"** (default), "Alexa", or
"Hey Mycroft" — pick it with `--wake-keyword hey_jarvis|alexa|hey_mycroft` or
`JARVIS_WAKE_KEYWORD`. A custom phrase such as "Noir" would require training a
new openWakeWord model and is not supported out of the box.

Use `--no-wake-word` for push-to-talk during development: hold **space** in the
Robot Brain window, or tap the arc reactor in the app.

### 4. Mobile app

```bash
cd jarvis_app
flutter pub get
flutter build apk --debug
# output: jarvis_app/build/app/outputs/flutter-apk/app-debug.apk
```

### 5. ESP32 firmware

Wi-Fi credentials and the brain's IP live in `backend/esp32/main/secrets.h`,
which is git-ignored. Create it from the template first:

```bash
cd backend/esp32
cp main/secrets.h.example main/secrets.h   # then edit SSID, password, SERVER_IP
idf.py set-target esp32
idf.py flash monitor
```

The board joins your Wi-Fi, connects out to the laptop on TCP port 9999, and
executes single-character commands (`F B L R S`). If no command arrives for
2 seconds it cuts the motors, so a crashed or disconnected brain cannot leave
the robot driving. The brain re-sends its current command every 0.5 s to keep
that failsafe satisfied during continuous driving.

---

## Security

- Secrets live in `.env` (backend) and `backend/esp32/main/secrets.h` (firmware). Both are git-ignored; neither is hard-coded.
- REST requests authenticate with `Authorization: Bearer <token>`, compared in constant time. A missing server key returns `503` instead of bypassing the check.
- SocketIO connections require a `token` at handshake time, through the query string or the auth dictionary.
- Model output and REST input are validated against the same Pydantic discriminated union. Only two action types exist (`move`, `mode`); movement is allow-listed to `{F, B, L, R, S}` and durations are clamped to `[0.1, JARVIS_MOVE_MAX_DURATION_S]` (5 s by default) in both the schema and the executor.
- `RobotComms` re-checks the allow-list at the socket boundary, so nothing outside `{F, B, L, R, S}` can reach the firmware.
- `RobotState` is guarded by an `RLock` and returns deep copies, so callers never hold a mutable reference to shared state.

---

## Testing

```bash
uv run pytest                 # full suite, coverage gate at 50%
cd jarvis_app && flutter test # Flutter widget + contract tests
```

93 Python tests across unit, integration, end-to-end and resilience suites, at
55% line coverage. The resilience suite drives real code paths (socket errors,
queue exhaustion, oversized payloads, thread restarts) rather than asserting on
constants.

---

## Roadmap

- **Near term:** sharpen object recognition and finish the remaining app screens.
- **Mid term:** multi-robot coordination and a cloud language model fallback.
- **Long term:** swarm behavior across several units.

---

<div align="center">
<sub>Final year engineering project. Built and maintained by Sahil.</sub>
</div>
