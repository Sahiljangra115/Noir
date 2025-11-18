import 'package:flutter/material.dart';
import 'boot_screen.dart';
import 'home_screen.dart';
import 'settings_screen.dart';

void main() {
  runApp(const JarvisApp());
}

class JarvisApp extends StatelessWidget {
  const JarvisApp({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'JARVIS Companion',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        primaryColor: Colors.white,
        scaffoldBackgroundColor: const Color(0xFF050505),
        colorScheme: const ColorScheme.dark(
          primary: Colors.white,
          secondary: Color(0xFF00E5FF),
          surface: Color(0xFF111111),
        ),
        fontFamily: 'Roboto', // Better if they had sf pro, but Roboto light works as default
        textTheme: const TextTheme(
          displayLarge: TextStyle(fontWeight: FontWeight.w200, letterSpacing: -1.5),
          bodyLarge: TextStyle(fontWeight: FontWeight.w300, letterSpacing: 0.5),
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.transparent,
          elevation: 0,
          centerTitle: true,
          iconTheme: IconThemeData(color: Colors.white70),
          titleTextStyle: TextStyle(fontSize: 16, fontWeight: FontWeight.w300, letterSpacing: 2, color: Colors.white),
        ),
      ),
      initialRoute: '/boot',
      routes: {
        '/boot': (context) => const BootScreen(),
        '/home': (context) => const HomeScreen(),
        '/settings': (context) => const SettingsScreen(),
      },
    );
  }
}