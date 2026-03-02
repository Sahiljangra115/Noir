import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'services/socket_service.dart';

class VisionScreen extends StatelessWidget {
  const VisionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        final state = socket.state;
        final accel = state.imu['accel'] ?? {'x': 0.0, 'y': 0.0, 'z': 0.0};
        final gps = state.gps;

        return Scaffold(
          appBar: AppBar(title: const Text('V I S I O N')),
          body: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('TELEMETRY FEED', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 2)),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: socket.isConnected ? Colors.green.withOpacity(0.1) : Colors.red.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        socket.isConnected ? 'LIVE' : 'OFFLINE',
                        style: TextStyle(color: socket.isConnected ? Colors.green : Colors.red, fontSize: 8, fontWeight: FontWeight.bold),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 30),
                _buildTelemetryItem('IMU Orientation', 
                  'X: ${accel['x'].toStringAsFixed(2)} Y: ${accel['y'].toStringAsFixed(2)} Z: ${accel['z'].toStringAsFixed(2)}'),
                const SizedBox(height: 30),
                _buildTelemetryItem('GPS Coordinates', 
                  'Lat: ${gps['lat'].toStringAsFixed(4)} Lon: ${gps['lon'].toStringAsFixed(4)}'),
                const Spacer(),
                Center(
                  child: Opacity(
                    opacity: 0.3,
                    child: Column(
                      children: [
                        const Icon(Icons.videocam_off, size: 40),
                        const SizedBox(height: 10),
                        const Text('Video streaming disabled for performance', style: TextStyle(fontSize: 10, letterSpacing: 1)),
                      ],
                    ),
                  ),
                ),
                const Spacer(),
              ],
            ),
          ),
          bottomNavigationBar: BottomNavigationBar(
            currentIndex: 2,
            onTap: (index) {
              if (index == 0) Navigator.pushReplacementNamed(context, '/');
              if (index == 1) Navigator.pushReplacementNamed(context, '/control');
              if (index == 3) Navigator.pushReplacementNamed(context, '/settings');
            },
            items: const [
              BottomNavigationBarItem(icon: Icon(Icons.blur_on), label: 'CORE'),
              BottomNavigationBarItem(icon: Icon(Icons.gamepad), label: 'CONTROL'),
              BottomNavigationBarItem(icon: Icon(Icons.visibility), label: 'VISION'),
              BottomNavigationBarItem(icon: Icon(Icons.settings), label: 'SYSTEM'),
            ],
          ),
        );
      }
    );
  }

  Widget _buildTelemetryItem(String label, String value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(color: Colors.white38, fontSize: 10, letterSpacing: 1)),
        const SizedBox(height: 8),
        Text(value, style: const TextStyle(color: Colors.white, fontSize: 16, fontFamily: 'monospace', fontWeight: FontWeight.w300)),
      ],
    );
  }
}
