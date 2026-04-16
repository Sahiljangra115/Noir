import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'widgets/ios_widgets.dart';
import 'services/socket_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _hostController = TextEditingController();
  final _tokenController = TextEditingController();

  @override
  void initState() {
    super.initState();
    final socket = Provider.of<SocketService>(context, listen: false);
    _hostController.text = socket.host;
    _tokenController.text = socket.token;
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        final accentColor = Theme.of(context).colorScheme.primary;

        return Scaffold(
          extendBody: true,
          extendBodyBehindAppBar: true,
          appBar: AppBar(title: const Text('S Y S T E M')),
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
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 24.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 20),
                    const Text('CONNECTIVITY', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 2)),
                    const SizedBox(height: 16),
                    GlassCard(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        children: [
                          _buildTextField('BRAIN IP ADDRESS', _hostController, Icons.lan_outlined, accentColor),
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 20),
                            child: Divider(color: Colors.white10, height: 1),
                          ),
                          _buildTextField('ACCESS TOKEN', _tokenController, Icons.vpn_key_outlined, accentColor, isSecret: true),
                        ],
                      ),
                    ),
                    const SizedBox(height: 32),
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: GestureDetector(
                        onTap: () async {
                          final host = _hostController.text.trim();
                          final token = _tokenController.text.trim();

                          if (host.isEmpty || !host.startsWith('http')) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text('Enter a valid host, e.g. http://192.168.1.10:5000'),
                                backgroundColor: Colors.redAccent,
                              ),
                            );
                            return;
                          }

                          if (token.isEmpty) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text('Access token is required.'),
                                backgroundColor: Colors.redAccent,
                              ),
                            );
                            return;
                          }

                          final prefs = await SharedPreferences.getInstance();
                          await prefs.setString('jarvis_host', host);
                          await prefs.setString('jarvis_token', token);

                          socket.updateConfig(host, token);
                          if (!context.mounted) return;
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text('System configuration synchronized.'),
                              backgroundColor: Colors.blueGrey,
                            ),
                          );
                        },
                        child: GlassCard(
                          padding: EdgeInsets.zero,
                          borderRadius: 16,
                          opacity: 0.1,
                          child: Center(
                            child: Text(
                              'SYNCHRONIZE',
                              style: TextStyle(color: accentColor, fontWeight: FontWeight.bold, letterSpacing: 2, fontSize: 13),
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 40),
                    const Text('MODEL INFO', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 2)),
                    const SizedBox(height: 16),
                    GlassCard(
                      padding: const EdgeInsets.all(20),
                      borderRadius: 20,
                      child: Row(
                        children: [
                          Icon(Icons.psychology_outlined, color: accentColor.withOpacity(0.5)),
                          const SizedBox(width: 16),
                          const Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('VLA ENGINE', style: TextStyle(color: Colors.white38, fontSize: 9, letterSpacing: 1)),
                              SizedBox(height: 4),
                              Text('Gemma 4 (System Optimized)', style: TextStyle(color: Colors.white, fontSize: 13)),
                            ],
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 150),
                  ],
                ),
              ),
            ),
          ),
          bottomNavigationBar: FloatingNav(
            currentIndex: 3,
            onTap: (index) {
              if (index == 0) Navigator.pushReplacementNamed(context, '/');
              if (index == 1) Navigator.pushReplacementNamed(context, '/control');
              if (index == 2) Navigator.pushReplacementNamed(context, '/vision');
            },
          ),
        );
      },
    );
  }

  @override
  void dispose() {
    _hostController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  Widget _buildTextField(String label, TextEditingController controller, IconData icon, Color accent, {bool isSecret = false}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(color: Colors.white30, fontSize: 9, letterSpacing: 1.5)),
        TextField(
          controller: controller,
          obscureText: isSecret,
          style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w300),
          decoration: InputDecoration(
            border: InputBorder.none,
            icon: Icon(icon, color: Colors.white24, size: 20),
            hintText: 'Enter value...',
            hintStyle: TextStyle(color: Colors.white.withOpacity(0.1), fontSize: 14),
          ),
        ),
      ],
    );
  }
}
