import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'widgets/particle_visualizer.dart';
import 'widgets/ios_widgets.dart';
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
        final accentColor = Theme.of(context).colorScheme.primary;
        
        return Scaffold(
          extendBody: true,
          extendBodyBehindAppBar: true,
          appBar: AppBar(
            title: const Text('C O R E'),
            actions: [
              Container(
                margin: const EdgeInsets.only(right: 20),
                child: Center(
                  child: Container(
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: socket.isConnected ? accentColor : Colors.redAccent,
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: (socket.isConnected ? accentColor : Colors.redAccent).withOpacity(0.5),
                          blurRadius: 10,
                          spreadRadius: 2,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
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
              bottom: false,
              child: Column(
                children: [
                  const Spacer(flex: 2),
                  
                  // Advanced Particle Visualizer (JARVIS Brain)
                  GestureDetector(
                    onTap: () {
                      if (socket.isConnected) {
                        socket.forceListen();
                        return;
                      }
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('Connect to JARVIS core first to use force-listen.'),
                          backgroundColor: Colors.redAccent,
                        ),
                      );
                    },
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        // Soft glow behind the brain
                        Container(
                          width: 200,
                          height: 200,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            boxShadow: [
                              BoxShadow(
                                color: accentColor.withOpacity(0.1),
                                blurRadius: 60,
                                spreadRadius: 10,
                              ),
                            ],
                          ),
                        ),
                        const ParticleVisualizer(),
                      ],
                    ),
                  ),
                  
                  const Spacer(flex: 2),
                  
                  // CONVERSATION LOG (Glassmorphic Card)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 24.0),
                    child: GlassCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                           Text(
                             "TRANSCRIPT", 
                             style: TextStyle(
                               color: Colors.white.withOpacity(0.3), 
                               fontSize: 10, 
                               fontWeight: FontWeight.w400, 
                               letterSpacing: 2
                             )
                           ),
                           const SizedBox(height: 12),
                           Text(
                             state.lastHeard.isEmpty ? "Waiting for voice..." : '"${state.lastHeard}"', 
                             style: TextStyle(
                               fontSize: 17, 
                               fontWeight: FontWeight.w300, 
                               color: Colors.white.withOpacity(0.6), 
                               fontStyle: FontStyle.italic
                             )
                           ),
                           const SizedBox(height: 32),
                           Text(
                             "AI RESPONSE", 
                             style: TextStyle(
                               color: accentColor.withOpacity(0.6), 
                               fontSize: 10, 
                               fontWeight: FontWeight.w400, 
                               letterSpacing: 2
                             )
                           ),
                           const SizedBox(height: 12),
                           Text(
                             state.jarvisResponse.isEmpty ? "System standby." : state.jarvisResponse, 
                             style: const TextStyle(
                               fontSize: 16, 
                               fontWeight: FontWeight.w300, 
                               color: Colors.white,
                               height: 1.4
                             )
                           ),
                        ],
                      ),
                    ),
                  ),
                  
                  const SizedBox(height: 130), // Padding for Floating Nav
                ],
              ),
            ),
          ),
          bottomNavigationBar: FloatingNav(
            currentIndex: 0,
            onTap: (index) {
              if (index == 1) Navigator.pushReplacementNamed(context, '/control');
              if (index == 2) Navigator.pushReplacementNamed(context, '/vision');
              if (index == 3) Navigator.pushReplacementNamed(context, '/settings');
            },
          ),
        );
      }
    );
  }
}
