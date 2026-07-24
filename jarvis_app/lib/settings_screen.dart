import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'config/app_config.dart';
import 'services/socket_service.dart';
import 'theme/app_theme.dart';
import 'theme/tokens.dart';
import 'widgets/hud.dart';

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
  void dispose() {
    _hostController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  void _toast(String msg, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: error ? Hud.red : Hud.panelHi,
    ));
  }

  Future<void> _sync(SocketService socket) async {
    final host = _hostController.text.trim();
    final token = _tokenController.text.trim();

    if (host.isEmpty || !host.startsWith('http')) {
      _toast('Enter a valid host, e.g. http://192.168.1.10:5000', error: true);
      return;
    }
    if (token.isEmpty) {
      _toast('Access token is required.', error: true);
      return;
    }

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(AppConfig.prefsHostKey, host);
    await prefs.setString(AppConfig.prefsTokenKey, token);
    socket.updateConfig(host, token);
    _toast('Configuration synchronized.');
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        return HudScreen(
          title: 'System',
          connected: socket.isConnected,
          children: [
            HudPanel(
              label: 'UPLINK',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _field('BRAIN IP ADDRESS', _hostController,
                      Icons.lan_outlined, 'http://192.168.1.10:5000'),
                  const SizedBox(height: Spacing.lg),
                  _field('ACCESS TOKEN', _tokenController,
                      Icons.vpn_key_outlined, 'bearer token',
                      secret: true),
                ],
              ),
            ),
            const SizedBox(height: Spacing.lg),
            HudButton(
              label: 'SYNCHRONIZE',
              icon: Icons.sync,
              active: true,
              expand: true,
              height: 56,
              onTap: () => _sync(socket),
            ),
            const SizedBox(height: Spacing.lg),
            HudPanel(
              label: 'CORE INFO',
              child: Column(
                children: [
                  HudReadout('LINK', socket.isConnected ? 'ONLINE' : 'OFFLINE',
                      valueColor: socket.isConnected ? Hud.green : Hud.red),
                  const HudReadout('VLA ENGINE', 'GEMMA 4'),
                  HudReadout('HOST', socket.host),
                ],
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _field(String label, TextEditingController controller, IconData icon,
      String hint,
      {bool secret = false}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        HudLabel(label, color: Hud.textDim, size: 9),
        TextField(
          controller: controller,
          obscureText: secret,
          cursorColor: Hud.amber,
          style: const TextStyle(
              color: Hud.textHi, fontSize: 14, fontFamily: Hud.mono),
          decoration: InputDecoration(
            isDense: true,
            icon: Icon(icon, color: Hud.textMid, size: 18),
            hintText: hint,
            hintStyle: const TextStyle(color: Hud.textDim, fontSize: 13),
            enabledBorder: const UnderlineInputBorder(
                borderSide: BorderSide(color: Hud.line)),
            focusedBorder: const UnderlineInputBorder(
                borderSide: BorderSide(color: Hud.amber)),
          ),
        ),
      ],
    );
  }
}
