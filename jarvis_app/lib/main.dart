import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'home_screen.dart';
import 'control_screen.dart';
import 'vision_screen.dart';
import 'settings_screen.dart';
import 'services/socket_service.dart';
import 'services/audio_service.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  
  final socketService = SocketService();
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
          surface: const Color(0xFF0A0A0A),
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.transparent,
          elevation: 0,
          centerTitle: true,
          titleTextStyle: TextStyle(
            color: Colors.white,
            fontSize: 16,
            fontWeight: FontWeight.w300,
            letterSpacing: 4,
          ),
        ),
        bottomNavigationBarTheme: const BottomNavigationBarThemeData(
          backgroundColor: Color(0xFF0A0A0A),
          selectedItemColor: Color(0xFF00E5FF),
          unselectedItemColor: Colors.white24,
          type: BottomNavigationBarType.fixed,
          elevation: 0,
          selectedLabelStyle: TextStyle(fontSize: 10, letterSpacing: 1, fontWeight: FontWeight.bold),
          unselectedLabelStyle: TextStyle(fontSize: 10, letterSpacing: 1),
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
