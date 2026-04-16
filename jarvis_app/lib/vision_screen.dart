import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'widgets/ios_widgets.dart';
import 'services/socket_service.dart';

class VisionScreen extends StatelessWidget {
  const VisionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        final state = socket.state;
        final accel = state.imu['accel'] is Map<String, dynamic>
            ? state.imu['accel'] as Map<String, dynamic>
            : {'x': 0.0, 'y': 0.0, 'z': 0.0};
        final gps = state.gps;
        final accentColor = Theme.of(context).colorScheme.primary;

        final accelX = _safeNum(accel['x']);
        final accelY = _safeNum(accel['y']);
        final accelZ = _safeNum(accel['z']);
        final gpsLat = _safeNum(gps['lat']);
        final gpsLon = _safeNum(gps['lon']);

        return Scaffold(
          extendBody: true,
          extendBodyBehindAppBar: true,
          appBar: AppBar(title: const Text('V I S I O N')),
          body: Container(
            width: double.infinity,
            height: double.infinity,
            decoration: const BoxDecoration(
              gradient: RadialGradient(
                colors: [Color(0xFF0A1A24), Color(0xFF000000)],
                center: Alignment.center,
                radius: 1.2,
              ),
            ),
            child: SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 10),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          'TELEMETRY FEED',
                          style: TextStyle(
                            color: Colors.white24,
                            fontSize: 10,
                            letterSpacing: 2,
                            fontWeight: FontWeight.w200,
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(
                            color: socket.isConnected ? accentColor.withOpacity(0.1) : Colors.red.withOpacity(0.1),
                            borderRadius: BorderRadius.circular(20),
                            border: Border.all(
                              color: (socket.isConnected ? accentColor : Colors.red).withOpacity(0.2),
                              width: 0.5,
                            ),
                          ),
                          child: Row(
                            children: [
                              Container(
                                width: 5,
                                height: 5,
                                decoration: BoxDecoration(
                                  color: socket.isConnected ? accentColor : Colors.red,
                                  shape: BoxShape.circle,
                                ),
                              ),
                              const SizedBox(width: 6),
                              Text(
                                socket.isConnected ? 'LIVE' : 'OFFLINE',
                                style: TextStyle(
                                  color: socket.isConnected ? accentColor : Colors.red,
                                  fontSize: 9,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 1,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 30),
                    GlassCard(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        children: [
                          _buildTelemetryItem(
                            'IMU ORIENTATION',
                            'X: ${accelX.toStringAsFixed(2)}  Y: ${accelY.toStringAsFixed(2)}  Z: ${accelZ.toStringAsFixed(2)}',
                            Icons.explore_outlined,
                          ),
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 20),
                            child: Divider(color: Colors.white10, height: 1),
                          ),
                          _buildTelemetryItem(
                            'GPS COORDINATES',
                            'LAT: ${gpsLat.toStringAsFixed(4)}  LON: ${gpsLon.toStringAsFixed(4)}',
                            Icons.location_on_outlined,
                          ),
                        ],
                      ),
                    ),
                    const Spacer(),
                    Center(
                      child: Column(
                        children: [
                          Icon(Icons.videocam_off_outlined, color: Colors.white.withOpacity(0.15), size: 48),
                          const SizedBox(height: 16),
                          Text(
                            'ENCRYPTED VIDEO LINK STANDBY',
                            style: TextStyle(
                              color: Colors.white.withOpacity(0.15),
                              fontSize: 10,
                              letterSpacing: 2,
                              fontWeight: FontWeight.w200,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            'Optimizing bandwidth for VLA processing',
                            style: TextStyle(
                              color: Colors.white.withOpacity(0.1),
                              fontSize: 9,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const Spacer(),
                    const SizedBox(height: 100),
                  ],
                ),
              ),
            ),
          ),
          bottomNavigationBar: FloatingNav(
            currentIndex: 2,
            onTap: (index) {
              if (index == 0) Navigator.pushReplacementNamed(context, '/');
              if (index == 1) Navigator.pushReplacementNamed(context, '/control');
              if (index == 3) Navigator.pushReplacementNamed(context, '/settings');
            },
          ),
        );
      },
    );
  }

  double _safeNum(dynamic value) {
    if (value is num) return value.toDouble();
    return 0.0;
  }

  Widget _buildTelemetryItem(String label, String value, IconData icon) {
    return Row(
      children: [
        Icon(icon, color: Colors.white24, size: 20),
        const SizedBox(width: 16),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: const TextStyle(color: Colors.white38, fontSize: 9, letterSpacing: 1.5)),
            const SizedBox(height: 6),
            Text(
              value,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 15,
                fontFamily: 'monospace',
                fontWeight: FontWeight.w300,
              ),
            ),
          ],
        ),
      ],
    );
  }
}
