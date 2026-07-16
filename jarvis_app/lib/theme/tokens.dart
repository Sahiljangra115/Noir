import 'package:flutter/material.dart';

class Spacing {
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;
  static const double xxl = 32;
  static const double xxxl = 48;
}

class Radii {
  static const double sm = 12;
  static const double md = 20;
  static const double lg = 28;
  static const double xl = 36;
}

class Motion {
  static const Duration fast = Duration(milliseconds: 150);
  static const Duration base = Duration(milliseconds: 220);
  static const Duration slow = Duration(milliseconds: 320);
  static const Cubic spring = Cubic(0.2, 0.9, 0.3, 1.0);
  static const Cubic easeOut = Cubic(0.16, 1.0, 0.3, 1.0);
}

class Elevation {
  static List<BoxShadow> ambient(int level, {bool isDark = false}) {
    final base = isDark ? Colors.black : Colors.black54;
    final blur = 8.0 * level;
    final spread = level * 0.5;
    return [
      BoxShadow(color: base.withValues(alpha: 0.18), blurRadius: blur, spreadRadius: spread, offset: Offset(0, level * 2.0)),
      BoxShadow(color: base.withValues(alpha: 0.06), blurRadius: blur * 2, spreadRadius: 0, offset: Offset(0, level * 4.0)),
    ];
  }
}

class AppTypography {
  static TextTheme scale(BuildContext ctx) {
    final tsf = MediaQuery.textScalerOf(ctx).scale(1.0).clamp(0.85, 1.6);
    final base = Theme.of(ctx).textTheme;
    return base.apply(fontSizeFactor: tsf);
  }
}
