import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'widgets/ios_widgets.dart';
import 'services/socket_service.dart';

class ControlScreen extends StatelessWidget {
  const ControlScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        final accentColor = Theme.of(context).colorScheme.primary;
        
        return Scaffold(
          extendBody: true,
          extendBodyBehindAppBar: true,
          appBar: AppBar(title: const Text('C O N T R O L')),
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
                padding: const EdgeInsets.symmetric(horizontal: 24.0),
                child: Column(
                  children: [
                    const SizedBox(height: 20),
                    GlassCard(
                      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                      borderRadius: 20,
                      child: _buildModeSelector(socket, accentColor),
                    ),
                    const Spacer(),
                    _buildControlPad(socket, accentColor),
                    const Spacer(),
                    Text(
                      socket.isConnected ? 'REMOTE LINK ACTIVE' : 'REMOTE LINK OFFLINE', 
                      style: TextStyle(
                        color: socket.isConnected
                            ? Colors.white.withOpacity(0.1)
                            : Colors.redAccent.withOpacity(0.6), 
                        fontSize: 10, 
                        fontWeight: FontWeight.w200,
                        letterSpacing: 4
                      )
                    ),
                    const SizedBox(height: 120),
                  ],
                ),
              ),
            ),
          ),
          bottomNavigationBar: FloatingNav(
            currentIndex: 1,
            onTap: (index) {
              if (index == 0) Navigator.pushReplacementNamed(context, '/');
              if (index == 2) Navigator.pushReplacementNamed(context, '/vision');
              if (index == 3) Navigator.pushReplacementNamed(context, '/settings');
            },
          ),
        );
      }
    );
  }

  Widget _buildModeSelector(SocketService socket, Color accentColor) {
    final modes = ['IDLE', 'LFR', 'HUMAN_TRACK', 'VLA', 'MANUAL'];
    final currentMode = modes.contains(socket.state.mode) ? socket.state.mode : 'IDLE';
    return DropdownButtonHideUnderline(
      child: DropdownButton<String>(
        value: currentMode,
        dropdownColor: const Color(0xFF151515),
        isExpanded: true,
        icon: Icon(Icons.keyboard_arrow_down_rounded, color: accentColor.withOpacity(0.5)),
        style: const TextStyle(
          color: Colors.white,
          fontSize: 14,
          fontWeight: FontWeight.w300,
          letterSpacing: 2
        ),
        items: modes.map((m) => DropdownMenuItem(
          value: m,
          child: Text(m),
        )).toList(),
        onChanged: (val) {
          if (val != null) socket.sendCommand('mode', val);
        },
      ),
    );
  }

  Widget _buildControlPad(SocketService socket, Color accentColor) {
    return Column(
      children: [
        _buildPadBtn(Icons.keyboard_arrow_up_rounded, 'F', socket, accentColor),
        const SizedBox(height: 10),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _buildPadBtn(Icons.keyboard_arrow_left_rounded, 'L', socket, accentColor),
            const SizedBox(width: 20),
            _buildPadBtn(Icons.stop_rounded, 'S', socket, Colors.redAccent, isStop: true),
            const SizedBox(width: 20),
            _buildPadBtn(Icons.keyboard_arrow_right_rounded, 'R', socket, accentColor),
          ],
        ),
        const SizedBox(height: 10),
        _buildPadBtn(Icons.keyboard_arrow_down_rounded, 'B', socket, accentColor),
      ],
    );
  }

  Widget _buildPadBtn(IconData icon, String cmd, SocketService socket, Color color, {bool isStop = false}) {
    return GestureDetector(
      onTapDown: (_) => socket.sendCommand('move', cmd),
      onTapUp: (_) => !isStop ? socket.sendCommand('move', 'S') : null,
      onTapCancel: () => !isStop ? socket.sendCommand('move', 'S') : null,
      child: GlassCard(
        padding: EdgeInsets.zero,
        borderRadius: 24,
        opacity: 0.06,
        child: Container(
          width: 80,
          height: 80,
          alignment: Alignment.center,
          child: Icon(
            icon, 
            color: color.withOpacity(0.8), 
            size: 36,
            shadows: [
              Shadow(
                color: color.withOpacity(0.3),
                blurRadius: 15,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
