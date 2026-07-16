import 'package:flutter/material.dart';

/// Tactical ground-control HUD palette. Dark-only, instrument-cluster
/// semantics: amber = primary data, green = healthy/OK, red = alarm.
class Hud {
  // Surfaces
  static const Color bg = Color(0xFF06080A); // near-black base
  static const Color panel = Color(0xFF0C1013); // raised frame fill
  static const Color panelHi = Color(0xFF11171B); // pressed / hover fill
  static const Color line = Color(0xFF1E262C); // hairline border
  static const Color lineHi = Color(0xFF2D3940); // brighter edge / corners

  // Data accents
  static const Color amber = Color(0xFFFFB000); // primary readout
  static const Color green = Color(0xFF35E08A); // link OK / healthy
  static const Color red = Color(0xFFFF4438); // E-stop / fault

  // Text
  static const Color textHi = Color(0xFFD6E0E6); // values, headings
  static const Color textMid = Color(0xFF7C8B94); // labels
  static const Color textDim = Color(0xFF46535B); // disabled / hints

  // ponytail: 'monospace' resolves to Roboto Mono on Android (our target).
  // Bundle a .ttf only if iOS/web ever need a guaranteed mono face.
  static const String mono = 'monospace';
}

class AppTheme {
  static ThemeData dark() => _build();
  // Dark-only HUD; light() returns the same so any system-theme caller is safe.
  static ThemeData light() => _build();

  static ThemeData _build() {
    final scheme = ColorScheme.fromSeed(
      seedColor: Hud.amber,
      brightness: Brightness.dark,
    ).copyWith(
      primary: Hud.amber,
      onPrimary: Hud.bg,
      secondary: Hud.green,
      error: Hud.red,
      surface: Hud.panel,
      onSurface: Hud.textHi,
    );

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: scheme,
      scaffoldBackgroundColor: Hud.bg,
      fontFamily: Hud.mono,
      splashFactory: NoSplash.splashFactory,
      highlightColor: Colors.transparent,
      visualDensity: VisualDensity.adaptivePlatformDensity,
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
        foregroundColor: Hud.textHi,
      ),
      textSelectionTheme: const TextSelectionThemeData(
        cursorColor: Hud.amber,
        selectionColor: Color(0x33FFB000),
        selectionHandleColor: Hud.amber,
      ),
      snackBarTheme: const SnackBarThemeData(
        backgroundColor: Hud.panelHi,
        contentTextStyle: TextStyle(
          color: Hud.textHi,
          fontFamily: Hud.mono,
          letterSpacing: 1,
          fontSize: 12,
        ),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }
}
