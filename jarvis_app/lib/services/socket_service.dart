import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:socket_io_client/socket_io_client.dart' as IO;
import '../models/robot_state.dart';

class SocketService extends ChangeNotifier {
  IO.Socket? _socket;
  RobotState _state = RobotState.initial();
  bool _isConnected = false;

  RobotState get state => _state;
  bool get isConnected => _isConnected;

  void connect(String url) {
    _socket?.dispose();
    
    _socket = IO.io(url, IO.OptionBuilder()
        .setTransports(['websocket'])
        .enableAutoConnect()
        .build());

    _socket?.onConnect((_) {
      _isConnected = true;
      notifyListeners();
    });

    _socket?.onDisconnect((_) {
      _isConnected = false;
      notifyListeners();
    });

    _socket?.on('state_update', (data) {
      if (data != null && data is Map<String, dynamic>) {
        _state = RobotState.fromJson(data);
        notifyListeners();
      }
    });

    // Audio playback callback would go here (Task 4)
  }

  void sendAudio(Uint8List data) {
    if (_isConnected) {
      _socket?.emit('audio_data', data);
    }
  }

  void sendTelemetry(Map<String, dynamic> data) {
    if (_isConnected) {
      _socket?.emit('sensor_data', data);
    }
  }

  void sendCommand(String type, dynamic value) {
    if (_isConnected) {
      _socket?.emit('command', {'type': type, 'value': value});
    }
  }

  void forceListen() {
    if (_isConnected) {
      _socket?.emit('force_listen', {});
    }
  }

  @override
  void dispose() {
    _socket?.dispose();
    super.dispose();
  }
}
