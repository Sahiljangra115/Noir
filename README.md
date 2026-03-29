# JARVIS: Autonomous Robot Assistant (v0.2.0)

JARVIS is a multi-modal autonomous robot assistant that combines Speech-to-Text (STT), Large Language Models (LLM), Text-to-Speech (TTS), and Computer Vision (CV) to create a seamless interactive experience. This project features a modular Python backend and a high-end Flutter mobile app for real-time control and telemetry.

## 🚀 Core Features

- **Voice Interaction:** Wake-word activation ("Jarvis"), reasoning-free LLM responses (Qwen 3.5), and low-latency speech synthesis.
- **Advanced Vision:** Real-time YOLOv8 person tracking, autonomous navigation via VLA, and hybrid ML+OpenCV line following.
- **Secure Control:** Token-based authentication for REST and WebSocket APIs, protected by rate limiting and CORS restrictions.
- **Mobile App:** iOS 26 + Shadcn styled Flutter app with a 3D spherical particle visualizer and full telemetry streaming.
- **Hardware Bridge:** TCP-based motor control for ESP32 with fallback safety states.

## 🛠️ Project Structure

- `backend/`: Core logic including API endpoints, hardware comms, and services (STT, TTS, etc.).
- `jarvis_app/`: Flutter mobile application for Android.
- `tests/`: Comprehensive E2E and Unit test suites, including security validation.
- `web_server.py`: Secure Flask-SocketIO server for mobile and dashboard integration.

## 🔧 Getting Started

### Prerequisites
- Python 3.12+ (managed via `uv` or `pip`)
- Flutter SDK (for mobile app)
- Android Studio (for building the APK)
- ESP32 hardware (optional, for physical robot control)

### Backend Setup
1. Install dependencies:
   ```bash
   uv pip install -e .
   ```
2. Configure environment:
   - Create a `.env` file from the provided template.
   - Add your `JARVIS_SECRET_KEY` and `PORCUPINE_ACCESS_KEY`.
3. Run the brain:
   ```bash
   python3 -m backend.main
   ```

### Mobile App Build
1. Open `jarvis_app` in Android Studio.
2. Run `flutter pub get`.
3. Build the APK via **Build > Flutter > Build APK** or:
   ```bash
   flutter build apk --debug
   ```

## 🔒 Security Note
Version 0.2.0 introduces mandatory token-based authentication. Ensure that all clients (mobile app, scripts) include the `Authorization: Bearer <your_key>` header for REST calls or provide the token during the SocketIO connection handshake.

## 📄 Documentation
- `ARCHITECTURE.md`: Detailed system design and flow.
- `PROJECT_STATUS.md`: Current version, features, and recent updates.
- `LEARNINGS.md`: Technical insights and build system troubleshooting.
- `Technical Difficulties and solution.md`: Advanced analysis of project challenges.
