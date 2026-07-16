import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Schematic top-down robot-car mark: chassis, 4 wheels, roof camera dome
/// with a sensor cone. Pure vector line-art — scales crisp at any size,
/// no raster asset. Front of the vehicle points up.
class RobotCarLogo extends StatelessWidget {
  final double size;
  final Color color;
  const RobotCarLogo({super.key, this.size = 26, this.color = Hud.amber});

  @override
  Widget build(BuildContext context) =>
      CustomPaint(size: Size.square(size), painter: _RobotCarPainter(color));
}

class _RobotCarPainter extends CustomPainter {
  final Color color;
  const _RobotCarPainter(this.color);

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width;
    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = math.max(1.5, s * 0.05)
      ..strokeJoin = StrokeJoin.round
      ..strokeCap = StrokeCap.round
      ..color = color;
    final fill = Paint()..color = color;
    Rect r(double l, double t, double rt, double b) =>
        Rect.fromLTRB(l * s, t * s, rt * s, b * s);

    // 4 wheels (protrude past the body sides)
    for (final w in [
      r(0.16, 0.24, 0.30, 0.42), // front-left
      r(0.70, 0.24, 0.84, 0.42), // front-right
      r(0.16, 0.58, 0.30, 0.76), // rear-left
      r(0.70, 0.58, 0.84, 0.76), // rear-right
    ]) {
      canvas.drawRRect(
          RRect.fromRectAndRadius(w, Radius.circular(s * 0.03)), stroke);
    }

    // chassis
    canvas.drawRRect(
        RRect.fromRectAndRadius(
            r(0.30, 0.16, 0.70, 0.86), Radius.circular(s * 0.08)),
        stroke);

    // front direction chevron
    final path = Path()
      ..moveTo(0.42 * s, 0.12 * s)
      ..lineTo(0.50 * s, 0.06 * s)
      ..lineTo(0.58 * s, 0.12 * s);
    canvas.drawPath(path, stroke);

    // sensor cone from the camera toward the front
    final cone = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = math.max(1, s * 0.03)
      ..color = color.withValues(alpha: 0.45);
    canvas.drawLine(Offset(0.50 * s, 0.50 * s), Offset(0.40 * s, 0.30 * s), cone);
    canvas.drawLine(Offset(0.50 * s, 0.50 * s), Offset(0.60 * s, 0.30 * s), cone);

    // camera dome + lens
    canvas.drawCircle(Offset(0.50 * s, 0.51 * s), s * 0.13, stroke);
    canvas.drawCircle(Offset(0.50 * s, 0.51 * s), s * 0.05, fill);
  }

  @override
  bool shouldRepaint(_RobotCarPainter old) => old.color != color;
}
