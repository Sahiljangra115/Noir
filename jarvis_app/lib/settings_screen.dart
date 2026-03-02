import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:provider/provider.dart';
import 'services/socket_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final TextEditingController _ipController = TextEditingController();
  final TextEditingController _portController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _ipController.text = prefs.getString('laptop_ip') ?? '192.168.1.100';
      _portController.text = prefs.getString('laptop_port') ?? '5000';
    });
  }

  Future<void> _saveSettings() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('laptop_ip', _ipController.text);
    await prefs.setString('laptop_port', _portController.text);
    
    if (mounted) {
      final url = 'http://${_ipController.text}:${_portController.text}';
      context.read<SocketService>().connect(url);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Connecting to JARVIS Core...')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('S Y S T E M')),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('CONNECTION', style: TextStyle(color: Colors.white24, fontSize: 10, letterSpacing: 2)),
            const SizedBox(height: 24),
            _buildTextField('Laptop IP Address', _ipController),
            const SizedBox(height: 16),
            _buildTextField('Port', _portController),
            const SizedBox(height: 32),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF00E5FF).withOpacity(0.1),
                foregroundColor: const Color(0xFF00E5FF),
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              onPressed: _saveSettings,
              child: const Text('LINK TO CORE', style: TextStyle(letterSpacing: 2, fontWeight: FontWeight.bold)),
            ),
            const Spacer(),
            const Center(
              child: Text('VERSION 1.0.0 ALPHA', style: TextStyle(color: Colors.white10, fontSize: 8, letterSpacing: 2)),
            ),
          ],
        ),
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: 3,
        onTap: (index) {
          if (index == 0) Navigator.pushReplacementNamed(context, '/');
          if (index == 1) Navigator.pushReplacementNamed(context, '/control');
          if (index == 2) Navigator.pushReplacementNamed(context, '/vision');
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

  Widget _buildTextField(String label, TextEditingController controller) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(color: Colors.white38, fontSize: 10)),
        const SizedBox(height: 8),
        TextField(
          controller: controller,
          style: const TextStyle(color: Colors.white, fontSize: 16, fontFamily: 'monospace'),
          decoration: InputDecoration(
            filled: true,
            fillColor: Colors.white.withOpacity(0.03),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
          ),
        ),
      ],
    );
  }
}
