import 'package:flutter/material.dart';
import 'dart:math';

class BootScreen extends StatefulWidget {
  const BootScreen({Key? key}) : super(key: key);

  @override
  State<BootScreen> createState() => _BootScreenState();
}

class _BootScreenState extends State<BootScreen> with TickerProviderStateMixin {
  late AnimationController _ringController;
  late AnimationController _fadeController;

  @override
  void initState() {
    super.initState();
    _ringController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
    )..forward();

    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..forward().then((_) {
        Future.delayed(const Duration(milliseconds: 1500), () {
          Navigator.of(context).pushReplacementNamed('/home');
        });
      });
  }

  @override
  void dispose() {
    _ringController.dispose();
    _fadeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            AnimatedBuilder(
              animation: _ringController,
              builder: (context, child) {
                return CustomPaint(
                  painter: MinimalRingPainter(_ringController.value),
                  size: const Size(120, 120),
                );
              },
            ),
            const SizedBox(height: 40),
            FadeTransition(
              opacity: _fadeController,
              child: const Text(
                'INITIALIZING SYSTEMS',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w200,
                  letterSpacing: 4,
                  color: Colors.white54,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class MinimalRingPainter extends CustomPainter {
  final double progress;
  MinimalRingPainter(this.progress);

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = size.width / 2;

    // Background track
    final trackPaint = Paint()
      ..color = Colors.white.withOpacity(0.05)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    canvas.drawCircle(center, radius, trackPaint);

    // Glowing progress
    final progressPaint = Paint()
      ..color = const Color(0xFF00E5FF).withOpacity(0.8)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..strokeCap = StrokeCap.round
      // Holographic glow effect
      ..maskFilter = const MaskFilter.blur(BlurStyle.solid, 4.0);

    final sweepAngle = 2 * pi * Curves.easeInOutCubic.transform(progress);
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      -pi / 2, // Start at top
      sweepAngle,
      false,
      progressPaint,
    );
    
    // Core dot fading in
    final corePaint = Paint()
      ..color = Colors.white.withOpacity(progress)
      ..style = PaintingStyle.fill;
    canvas.drawCircle(center, 2.0, corePaint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}