import 'dart:math';
import 'package:flutter/material.dart';

class ParticleVisualizer extends StatefulWidget {
  final bool isActive;
  const ParticleVisualizer({super.key, this.isActive = true});

  @override
  State<ParticleVisualizer> createState() => _ParticleVisualizerState();
}

class _ParticleVisualizerState extends State<ParticleVisualizer> with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  final List<Particle> _particles = [];
  final Random _random = Random();
  final int _particleCount = 40;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 20),
    )..repeat();

    for (int i = 0; i < _particleCount; i++) {
      _particles.add(Particle.random(_random));
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return CustomPaint(
          painter: ParticlePainter(_particles, _controller.value),
          size: const Size(250, 250),
        );
      },
    );
  }
}

class Particle {
  final double theta; // horizontal angle
  final double phi;   // vertical angle
  final double radius;
  final double size;
  final double speed;

  Particle({required this.theta, required this.phi, required this.radius, required this.size, required this.speed});

  factory Particle.random(Random random) {
    return Particle(
      theta: random.nextDouble() * 2 * pi,
      phi: random.nextDouble() * pi,
      radius: 60 + random.nextDouble() * 40,
      size: 1 + random.nextDouble() * 2,
      speed: 0.5 + random.nextDouble() * 1.5,
    );
  }
}

class ParticlePainter extends CustomPainter {
  final List<Particle> particles;
  final double animationValue;

  ParticlePainter(this.particles, this.animationValue);

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final paint = Paint()..color = const Color(0xFF00E5FF);
    
    // Core Glow
    final corePaint = Paint()
      ..color = const Color(0xFF00E5FF).withOpacity(0.4)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 15);
    canvas.drawCircle(center, 25, corePaint);

    final rotationY = animationValue * 2 * pi;
    final rotationX = animationValue * pi;

    for (var p in particles) {
      // 3D Spherical to Cartesian
      double x = p.radius * sin(p.phi) * cos(p.theta + rotationY * p.speed);
      double y = p.radius * sin(p.phi + rotationX * 0.2) * sin(p.theta + rotationY * p.speed);
      double z = p.radius * cos(p.phi + rotationX * 0.2);

      // Simple 3D to 2D projection with perspective
      double perspective = (z + 150) / 300;
      double projectedX = x * perspective;
      double projectedY = y * perspective;
      
      double opacity = (z + p.radius) / (2 * p.radius);
      paint.color = const Color(0xFF00E5FF).withOpacity(opacity.clamp(0.1, 0.8));
      
      canvas.drawCircle(
        Offset(center.dx + projectedX, center.dy + projectedY),
        p.size * perspective * 2,
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}
