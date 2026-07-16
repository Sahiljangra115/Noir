import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' show PointMode;
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// "God particle" amber sphere: a fibonacci point-cloud carved into clumps
/// and voids by summed-sine noise, spun on yaw + a slow pitch wobble, shaded
/// top(pale gold) -> bottom(deep ember) with depth/twinkle brightness.
///
/// Native CustomPainter port of the HTML/canvas original. Points are bucketed
/// by (colour band, brightness) and flushed with drawRawPoints — a handful of
/// draw calls per frame instead of one-per-particle, so it stays at 60fps on
/// a phone. Same contract as the orb it replaces: amber when [active], dim
/// grey offline; [onTap] force-listens.
class GodParticleOrb extends StatefulWidget {
  final bool active;
  final VoidCallback onTap;
  final double size;
  const GodParticleOrb({
    super.key,
    required this.active,
    required this.onTap,
    required this.size,
  });

  @override
  State<GodParticleOrb> createState() => _GodParticleOrbState();
}

class _GodParticleOrbState extends State<GodParticleOrb>
    with SingleTickerProviderStateMixin {
  // One slow loop drives the spin phase; 24s feels like a planet, not a fan.
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(seconds: 24))
        ..repeat();

  late final List<_P> _pts = _buildSphere();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: widget.onTap,
      child: SizedBox(
        width: widget.size,
        height: widget.size,
        child: AnimatedBuilder(
          animation: _c,
          builder: (_, __) => CustomPaint(
            painter: _ParticlePainter(_pts, _c.value, widget.active),
          ),
        ),
      ),
    );
  }
}

// ── Point cloud ──────────────────────────────────────────────────────────────

class _P {
  final double x, y, z; // unit-ish sphere position (noise-perturbed shell)
  final int band; // 0..CB-1 colour band, top pale -> bottom ember
  final double twPhase, twSpeed, grain; // per-point twinkle + grain
  _P(this.x, this.y, this.z, this.band, this.twPhase, this.twSpeed, this.grain);
}

const int _cb = 6; // colour bands
const int _bl = 8; // brightness levels

/// Cheap pseudo-3D noise (summed sines) — clumps, voids, shell turbulence.
double _noise(double x, double y, double z) =>
    (math.sin(x * 1.7 + y * 0.6) +
        math.sin(y * 1.9 + z * 0.7) +
        math.sin(z * 1.5 + x * 0.8) +
        0.6 * math.sin((x + y) * 2.6 + 1.3) +
        0.5 * math.sin((y + z) * 3.1 - 0.7)) /
    3.2; // ~[-1,1]

List<_P> _buildSphere() {
  // Fixed seed -> identical cloud every build, so hot-reload doesn't reshuffle.
  final rng = math.Random(7);
  const n = 2200; // dense enough on a ~320px orb, light enough for mobile
  final ga = math.pi * (1 + math.sqrt(5));
  final out = <_P>[];
  for (var i = 0; i < n; i++) {
    final k = i + 0.5;
    final phi = math.acos(1 - 2 * k / n);
    final th = ga * k;
    final x = math.sin(phi) * math.cos(th);
    final y = math.cos(phi);
    final z = math.sin(phi) * math.sin(th);
    final nl = _noise(x * 2.1, y * 2.1, z * 2.1); // low-freq density + bulge
    final nh = _noise(x * 6.0, y * 6.0, z * 6.0); // high-freq grain
    final dens = 0.45 + 0.5 * nl + 0.18 * nh; // keep probability
    if (rng.nextDouble() > dens) continue; // carve voids
    final r = 1 + 0.13 * nl + 0.04 * nh; // turbulent shell thickness
    final colorT = 1 - (y + 1) / 2; // top pale, bottom ember
    final band = (colorT * (_cb - 1)).round().clamp(0, _cb - 1);
    out.add(_P(
      x * r,
      y * r,
      z * r,
      band,
      rng.nextDouble() * 6.28,
      rng.nextDouble() * 0.04 + 0.02,
      0.6 + 0.4 * nh,
    ));
  }
  return out;
}

// ── Painter ──────────────────────────────────────────────────────────────────

class _ParticlePainter extends CustomPainter {
  final List<_P> pts;
  final double t; // 0..1 spin phase
  final bool active;
  _ParticlePainter(this.pts, this.t, this.active);

  // Amber ramp: pale gold (top) -> deep ember (bottom). Offline = cold grey.
  static const List<List<double>> _amberStops = [
    [255, 236, 200],
    [255, 196, 110],
    [255, 150, 52],
    [226, 96, 28],
    [150, 52, 18],
  ];
  static const List<List<double>> _greyStops = [
    [120, 134, 142],
    [86, 99, 107],
    [64, 75, 82],
    [48, 57, 63],
    [34, 41, 46],
  ];

  static List<double> _grad(List<List<double>> s, double tt) {
    tt = tt.clamp(0.0, 1.0);
    final p = tt * (s.length - 1);
    final i = p.floor().clamp(0, s.length - 2);
    final f = p - i;
    final a = s[i], b = s[i + 1];
    return [
      a[0] + (b[0] - a[0]) * f,
      a[1] + (b[1] - a[1]) * f,
      a[2] + (b[2] - a[2]) * f,
    ];
  }

  // Colour lookup [band][brightnessLevel]; rebuilt only when `active` flips
  // would be ideal, but it's 48 cheap allocs — fine to build per paint.
  List<List<Paint>> _table(double base) {
    final stops = active ? _amberStops : _greyStops;
    return List.generate(_cb, (c) {
      final col = _grad(stops, c / (_cb - 1));
      return List.generate(_bl, (b) {
        final f = (b + 0.6) / _bl;
        return Paint()
          ..color = Color.fromARGB(
              255, (col[0] * f).toInt(), (col[1] * f).toInt(), (col[2] * f).toInt())
          ..strokeCap = StrokeCap.round
          // brighter bucket = nearer/front = larger dot (depth correlates).
          ..strokeWidth = base * (0.7 + (b / (_bl - 1)) * 1.25);
      });
    });
  }

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2, cy = size.height / 2;
    final rr = size.shortestSide * 0.42;
    final base = math.max(1.4, rr * 0.014);
    final tint = active ? Hud.amber : Hud.textDim;

    // warm halo bloom behind the cloud
    final haloR = rr * 1.9;
    canvas.drawCircle(
      Offset(cx, cy),
      haloR,
      Paint()
        ..shader = RadialGradient(
          colors: [
            tint.withValues(alpha: active ? 0.16 : 0.06),
            tint.withValues(alpha: active ? 0.05 : 0.02),
            Colors.transparent,
          ],
          stops: const [0.0, 0.45, 1.0],
        ).createShader(Rect.fromCircle(center: Offset(cx, cy), radius: haloR)),
    );

    // rotation: yaw (spin) about Y, slow pitch wobble about X
    final ya = t * 2 * math.pi;
    final pa = 0.22 + 0.14 * math.sin(ya * 0.5);
    final cyaw = math.cos(ya), syaw = math.sin(ya);
    final cpit = math.cos(pa), spit = math.sin(pa);

    // bucket point coords by (band, brightness); growable lists keep capacity
    // across frames (length=0 doesn't free backing array) -> low GC churn.
    final buckets = List.generate(_cb * _bl, (_) => <double>[]);
    final tw2pi = t * 2 * math.pi;

    for (final p in pts) {
      // yaw about Y
      final rx = p.x * cyaw - p.z * syaw;
      final rz = p.x * syaw + p.z * cyaw;
      // pitch about X
      final ry2 = p.y * cpit - rz * spit;
      final rz2 = p.y * spit + rz * cpit;
      final front = (rz2 + 1) / 2; // 0 back .. 1 front
      final persp = 1 / (1 - rz2 * 0.22);
      final sx = cx + rx * rr * persp;
      final sy = cy + ry2 * rr * persp;
      final tw = 0.7 + 0.3 * math.sin(p.twPhase + tw2pi * (p.twSpeed * 12));
      final b = (0.22 + 0.78 * front) * p.grain * tw; // depth + grain + twinkle
      if (b < 0.05) continue;
      var bl = (b * _bl).toInt();
      if (bl > _bl - 1) bl = _bl - 1;
      final arr = buckets[p.band * _bl + bl];
      arr.add(sx);
      arr.add(sy);
    }

    final table = _table(base);
    for (var c = 0; c < _cb; c++) {
      for (var b = 0; b < _bl; b++) {
        final arr = buckets[c * _bl + b];
        if (arr.isEmpty) continue;
        canvas.drawRawPoints(
          PointMode.points,
          Float32List.fromList(arr),
          table[c][b],
        );
      }
    }
  }

  @override
  bool shouldRepaint(_ParticlePainter old) =>
      old.t != t || old.active != active;
}
