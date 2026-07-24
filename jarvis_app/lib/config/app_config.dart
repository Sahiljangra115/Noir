/// Central app constants.
///
/// Values here mirror the backend contract:
/// - [modes] must match RobotMode in backend/main.py
/// - event names must match the SocketIO contract in web_server.py
/// - [framePath] must match the authed MJPEG route in web_server.py
class AppConfig {
  AppConfig._();

  // Connection
  static const defaultHost = 'http://localhost:5000';
  static const prefsHostKey = 'jarvis_host';
  static const prefsTokenKey = 'jarvis_token';

  // Backend routes
  static const framePath = '/frame';

  // Robot modes (RobotMode enum, backend/main.py)
  static const modes = ['IDLE', 'LFR', 'HUMAN_TRACK', 'VLA', 'MANUAL'];
  static const fallbackMode = 'IDLE';

  // Command payload
  static const moveDurationSecs = 1.0;

  // Audio (voice pipeline expects PCM16 mono 16 kHz)
  static const micSampleRate = 16000;

  // SocketIO events (web_server.py)
  static const evStateUpdate = 'state_update';
  static const evAudioData = 'audio_data';
  static const evSensorData = 'sensor_data';
  static const evCommand = 'command';
  static const evForceListen = 'force_listen';
}
