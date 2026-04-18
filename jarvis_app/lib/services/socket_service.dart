import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:socket_io_client/socket_io_client.dart' as IO;
import '../models/robot_state.dart';

class SocketService extends ChangeNotifier {
  IO.Socket? _socket;
  RobotState _state = RobotState.initial();
  bool _isConnected = false;
  String? _connectionError;
  
  String _host = 'http://localhost:5000';
  String _token = '';

  RobotState get state => _state;
  bool get isConnected => _isConnected;
  String? get connectionError => _connectionError;
  String get host => _host;
  String get token => _token;

  void updateConfig(String newHost, String newToken) {
    _host = newHost;
    _token = newToken;
    connect(_host, token: _token);
    notifyListeners();
  }

  void connect(String url, {String? token}) {
    _host = url;
    _token = token ?? '';
    _socket?.dispose();

    final handshakeToken = _token.trim();
    
    _socket = IO.io(url, IO.OptionBuilder()
        .setTransports(['websocket'])
        .setAuth({'token': handshakeToken}) // For SocketIO 4+ handshake
        .setQuery({'token': handshakeToken}) // Fallback for some configurations
        .enableAutoConnect()
        .build());

    _socket?.onConnect((_) {
      _isConnected = true;
      _connectionError = null;
      notifyListeners();
      print('Connected to JARVIS Core');
    });

    _socket?.onConnectError((data) {
      _isConnected = false;
      _connectionError = data.toString();
      notifyListeners();
      print('Connection Error: $data');
    });

    _socket?.onConnectTimeout((data) {
      _isConnected = false;
      _connectionError = 'Connection Timeout';
      notifyListeners();
      print('Connection Timeout');
    });

    _socket?.onDisconnect((_) {
      _isConnected = false;
      notifyListeners();
      print('Disconnected from JARVIS Core');
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
      if (type == 'mode') {
        _socket?.emit('command', {'type': 'mode', 'value': value});
      } else if (type == 'move') {
        _socket?.emit('command', {'type': 'move', 'cmd': value, 'duration': 1.0});
      }
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
