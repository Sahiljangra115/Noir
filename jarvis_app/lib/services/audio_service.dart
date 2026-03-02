import 'dart:async';
import 'package:record/record.dart';
import 'package:sensors_plus/sensors_plus.dart';
import 'package:geolocator/geolocator.dart';
import 'socket_service.dart';

class AudioService {
  final AudioRecorder _recorder = AudioRecorder();
  final SocketService socket;
  StreamSubscription? _audioSubscription;
  StreamSubscription? _imuSubscription;
  StreamSubscription? _gpsSubscription;

  AudioService(this.socket);

  Future<void> start() async {
    if (await _recorder.hasPermission()) {
      final stream = await _recorder.startStream(const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 16000,
        numChannels: 1,
      ));

      _audioSubscription = stream.listen((data) {
        socket.sendAudio(data);
      });
    }

    // Start IMU telemetry
    _imuSubscription = accelerometerEventStream().listen((event) {
      socket.sendTelemetry({
        'imu': {
          'accel': {'x': event.x, 'y': event.y, 'z': event.z},
          'gyro': {'x': 0.0, 'y': 0.0, 'z': 0.0}
        }
      });
    });

    // Start GPS telemetry
    _gpsSubscription = Geolocator.getPositionStream().listen((pos) {
      socket.sendTelemetry({
        'gps': {'lat': pos.latitude, 'lon': pos.longitude}
      });
    });
  }

  void stop() {
    _audioSubscription?.cancel();
    _imuSubscription?.cancel();
    _gpsSubscription?.cancel();
    _recorder.stop();
  }

  void dispose() {
    stop();
    _recorder.dispose();
  }
}
