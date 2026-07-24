import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'home_screen.dart';
import 'control_screen.dart';
import 'vision_screen.dart';
import 'settings_screen.dart';
import 'config/app_config.dart';
import 'services/socket_service.dart';
import 'services/audio_service.dart';
import 'theme/app_theme.dart';
import 'utils/responsive.dart';
import 'widgets/hud.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: Hud.bg,
  ));

  final socketService = SocketService();
  final prefs = await SharedPreferences.getInstance();
  final savedHost =
      prefs.getString(AppConfig.prefsHostKey) ?? socketService.host;
  final savedToken = prefs.getString(AppConfig.prefsTokenKey) ?? '';

  socketService.updateConfig(savedHost, savedToken);

  final audioService = AudioService(socketService);
  audioService.start();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: socketService),
        Provider.value(value: audioService),
      ],
      child: const JarvisApp(),
    ),
  );
}

class JarvisApp extends StatelessWidget {
  const JarvisApp({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = AppTheme.dark();
    return MaterialApp(
      title: 'JARVIS',
      debugShowCheckedModeBanner: false,
      theme: theme,
      darkTheme: theme,
      themeMode: ThemeMode.dark,
      home: const _AppShell(),
    );
  }
}

/// Root shell that owns the nav index and switches pages.
class _AppShell extends StatefulWidget {
  const _AppShell();

  @override
  State<_AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<_AppShell> {
  int _index = 0;

  static const _navItems = [
    HudNavItem(icon: Icons.radar, label: 'Core'),
    HudNavItem(icon: Icons.open_with, label: 'Control'),
    HudNavItem(icon: Icons.videocam_outlined, label: 'Vision'),
    HudNavItem(icon: Icons.tune, label: 'System'),
  ];

  static const _pages = <Widget>[
    HomeScreen(),
    ControlScreen(),
    VisionScreen(),
    SettingsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final useRail = context.ff != FormFactor.compact;

    final body = AnimatedSwitcher(
      duration: const Duration(milliseconds: 200),
      child: KeyedSubtree(key: ValueKey(_index), child: _pages[_index]),
    );

    return Scaffold(
      backgroundColor: Hud.bg,
      resizeToAvoidBottomInset: true,
      bottomNavigationBar: useRail
          ? null
          : HudNavBar(
              items: _navItems, currentIndex: _index, onChanged: _onNav),
      body: SafeArea(
        bottom: false,
        child: useRail
            ? Row(
                children: [
                  HudRail(
                      items: _navItems,
                      currentIndex: _index,
                      onChanged: _onNav),
                  Expanded(child: body),
                ],
              )
            : body,
      ),
    );
  }

  void _onNav(int i) {
    if (i != _index) setState(() => _index = i);
  }
}
