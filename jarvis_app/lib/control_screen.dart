import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'services/socket_service.dart';

class ControlScreen extends StatelessWidget {
  const ControlScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        return Scaffold(
          appBar: AppBar(title: const Text('C O N T R O L')),
          body: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24.0),
            child: Column(
              children: [
                const SizedBox(height: 40),
                _buildModeSelector(socket),
                const Spacer(),
                _buildControlPad(socket),
                const Spacer(),
                const Text('REMOTE LINK ACTIVE', style: TextStyle(color: Colors.white10, fontSize: 10, letterSpacing: 4)),
                const SizedBox(height: 40),
              ],
            ),
          ),
          bottomNavigationBar: BottomNavigationBar(
            currentIndex: 1,
            onTap: (index) {
              if (index == 0) Navigator.pushReplacementNamed(context, '/');
              if (index == 2) Navigator.pushReplacementNamed(context, '/vision');
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

  Widget _buildModeSelector(SocketService socket) {
    final modes = ['IDLE', 'LFR', 'HUMAN_TRACK', 'VLA', 'MANUAL'];
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.03),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.05)),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: socket.state.mode,
          dropdownColor: const Color(0xFF0A0A0A),
          isExpanded: true,
          items: modes.map((m) => DropdownMenuItem(
            value: m,
            child: Text(m, style: const TextStyle(fontSize: 14, letterSpacing: 1)),
          )).toList(),
          onChanged: (val) {
            if (val != null) socket.sendCommand('mode', val);
          },
        ),
      ),
    );
  }

  Widget _buildControlPad(SocketService socket) {
    return Column(
      children: [
        _buildPadBtn(Icons.arrow_upward, 'F', socket),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _buildPadBtn(Icons.arrow_back, 'L', socket),
            const SizedBox(width: 20),
            _buildPadBtn(Icons.stop, 'S', socket, isStop: true),
            const SizedBox(width: 20),
            _buildPadBtn(Icons.arrow_forward, 'R', socket),
          ],
        ),
        _buildPadBtn(Icons.arrow_downward, 'B', socket),
      ],
    );
  }

  Widget _buildPadBtn(IconData icon, String cmd, SocketService socket, {bool isStop = false}) {
    return GestureDetector(
      onTapDown: (_) => socket.sendCommand('move', cmd),
      onTapUp: (_) => !isStop ? socket.sendCommand('move', 'S') : null,
      child: Container(
        margin: const EdgeInsets.all(10),
        width: 70,
        height: 70,
        decoration: BoxDecoration(
          color: isStop ? Colors.red.withOpacity(0.1) : Colors.white.withOpacity(0.03),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: isStop ? Colors.red.withOpacity(0.3) : Colors.white.withOpacity(0.05)),
        ),
        child: Icon(icon, color: isStop ? Colors.redAccent : const Color(0xFF00E5FF), size: 30),
      ),
    );
  }
}
