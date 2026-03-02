class RobotState {
  final String mode;
  final String lastCmd;
  final String lastHeard;
  final String jarvisResponse;
  final bool phoneConnected;
  final Map<String, dynamic> imu;
  final Map<String, dynamic> gps;

  RobotState({
    required this.mode,
    required this.lastCmd,
    required this.lastHeard,
    required this.jarvisResponse,
    required this.phoneConnected,
    required this.imu,
    required this.gps,
  });

  factory RobotState.initial() {
    return RobotState(
      mode: 'IDLE',
      lastCmd: 'S',
      lastHeard: '...',
      jarvisResponse: 'Online and ready.',
      phoneConnected: false,
      imu: {'accel': {'x': 0.0, 'y': 0.0, 'z': 0.0}},
      gps: {'lat': 0.0, 'lon': 0.0},
    );
  }

  factory RobotState.fromJson(Map<String, dynamic> json) {
    return RobotState(
      mode: json['mode'] ?? 'IDLE',
      lastCmd: json['last_cmd'] ?? 'S',
      lastHeard: json['last_heard'] ?? '...',
      jarvisResponse: json['jarvis_response'] ?? '',
      phoneConnected: json['phone_connected'] ?? false,
      imu: json['imu'] ?? {'accel': {'x': 0.0, 'y': 0.0, 'z': 0.0}},
      gps: json['gps'] ?? {'lat': 0.0, 'lon': 0.0},
    );
  }
}
