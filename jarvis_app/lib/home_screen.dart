import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'widgets/particle_visualizer.dart';
import 'services/socket_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        final state = socket.state;
        
        return Scaffold(
          extendBodyBehindAppBar: true,
          appBar: AppBar(
            title: const Text('C O R E'),
            actions: [
              IconButton(
                icon: Icon(
                  Icons.radio_button_checked,
                  size: 14,
                  color: socket.isConnected ? const Color(0xFF00E5FF) : Colors.redAccent,
                ),
                onPressed: () {},
              ),
              const SizedBox(width: 8),
            ],
          ),
          body: Container(
            decoration: const BoxDecoration(
              gradient: RadialGradient(
                colors: [Color(0xFF101A24), Color(0xFF000000)],
                center: Alignment.center,
                radius: 1.5,
              ),
            ),
            child: SafeArea(
              child: Column(
                children: [
                  const Spacer(flex: 1),
                  // Advanced Particle Visualizer
                  GestureDetector(
                    onTap: () => socket.forceListen(),
                    child: const Center(
                      child: ParticleVisualizer(),
                    ),
                  ),
                  const Spacer(flex: 1),
                  
                  // CONVERSATION LOG
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 24.0),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(24),
                      child: BackdropFilter(
                        filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
                        child: Container(
                          padding: const EdgeInsets.all(24),
                          decoration: BoxDecoration(
                            color: Colors.white.withOpacity(0.03),
                            borderRadius: BorderRadius.circular(24),
                            border: Border.all(color: Colors.white.withOpacity(0.05)),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                               Text(
                                 "TRANSCRIPT", 
                                 style: TextStyle(color: Colors.white.withOpacity(0.3), fontSize: 9, fontWeight: FontWeight.w400, letterSpacing: 2)
                               ),
                               const SizedBox(height: 12),
                               Text(
                                 '"${state.lastHeard}"', 
                                 style: TextStyle(fontSize: 16, fontWeight: FontWeight.w300, color: Colors.white.withOpacity(0.7), fontStyle: FontStyle.italic)
                               ),
                               const SizedBox(height: 24),
                               Text(
                                 "AI RESPONSE", 
                                 style: TextStyle(color: const Color(0xFF00E5FF).withOpacity(0.5), fontSize: 9, fontWeight: FontWeight.w400, letterSpacing: 2)
                               ),
                               const SizedBox(height: 12),
                               Text(
                                 state.jarvisResponse, 
                                 style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w300, color: Colors.white)
                               ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 40),
                ],
              ),
            ),
          ),
          bottomNavigationBar: BottomNavigationBar(
            currentIndex: 0,
            onTap: (index) {
              if (index == 1) Navigator.pushReplacementNamed(context, '/control');
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
}
