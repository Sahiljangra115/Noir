import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'home_screen.dart';
import 'control_screen.dart';
import 'vision_screen.dart';
import 'settings_screen.dart';
import 'services/socket_service.dart';
import 'services/audio_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  final socketService = SocketService();
  final prefs = await SharedPreferences.getInstance();
  final savedHost = prefs.getString('jarvis_host') ?? socketService.host;
  final savedToken = prefs.getString('jarvis_token') ?? '';

  socketService.updateConfig(savedHost, savedToken);

  final audioService = AudioService(socketService);

  // Start audio/telemetry pipeline
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
    return MaterialApp(
      title: 'JARVIS',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: Colors.black,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF00E5FF),
          brightness: Brightness.dark,
          surface: const Color(0xFF050505),
        ),
        textTheme: const TextTheme(
          displayLarge: TextStyle(
            color: Colors.white,
            fontSize: 32,
            fontWeight: FontWeight.w200,
            letterSpacing: -0.5,
          ),
          bodyMedium: TextStyle(
            color: Colors.white,
            fontSize: 15,
            fontWeight: FontWeight.w300,
            height: 1.5,
          ),
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.transparent,
          elevation: 0,
          centerTitle: true,
          titleTextStyle: TextStyle(
            color: Colors.white,
            fontSize: 14,
            fontWeight: FontWeight.w200,
            letterSpacing: 6,
          ),
        ),
      ),
      initialRoute: '/',
      routes: {
        '/': (context) => const HomeScreen(),
        '/control': (context) => const ControlScreen(),
        '/vision': (context) => const VisionScreen(),
        '/settings': (context) => const SettingsScreen(),
      },
    );
  }
}
