import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'logo.dart';

/// Tactical HUD widget kit. Bracket-cornered panels, mono readouts,
/// segmented gauges, a radar listen-reticle and bracketed nav.
/// Visual identity only — all data still flows through SocketService.

// ── Text helpers ────────────────────────────────────────────────────────────

/// Dim, wide-tracked uppercase label (the "stencil" look).
class HudLabel extends StatelessWidget {
  final String text;
  final Color? color;
  final double size;
  const HudLabel(this.text, {super.key, this.color, this.size = 10});

  @override
  Widget build(BuildContext context) => Text(
        text.toUpperCase(),
        style: TextStyle(
          color: color ?? Hud.textMid,
          fontSize: size,
          letterSpacing: 2.5,
          fontWeight: FontWeight.w500,
          fontFamily: Hud.mono,
        ),
      );
}

// ── Panel with bracket corners ───────────────────────────────────────────────

class HudPanel extends StatelessWidget {
  final String? label;
  final Widget child;
  final EdgeInsets padding;
  final Color accent;
  const HudPanel({
    super.key,
    this.label,
    required this.child,
    this.padding = const EdgeInsets.all(Spacing.lg),
    this.accent = Hud.amber,
  });

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _BracketPainter(accent),
      child: Container(
        decoration: const BoxDecoration(color: Hud.panel),
        padding: padding,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (label != null) ...[
              Row(
                children: [
                  Container(width: 6, height: 6, color: accent),
                  const SizedBox(width: Spacing.sm),
                  HudLabel(label!, color: Hud.textMid),
                ],
              ),
              const SizedBox(height: Spacing.md),
              const _Hairline(),
              const SizedBox(height: Spacing.md),
            ],
            child,
          ],
        ),
      ),
    );
  }
}

/// Thin border + L-shaped corner brackets.
class _BracketPainter extends CustomPainter {
  final Color accent;
  const _BracketPainter(this.accent);

  @override
  void paint(Canvas canvas, Size size) {
    final border = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = Hud.line;
    canvas.drawRect(Offset.zero & size, border);

    final bracket = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..color = accent;
    const len = 12.0;
    void corner(Offset o, Offset h, Offset v) {
      canvas.drawLine(o, o + h, bracket);
      canvas.drawLine(o, o + v, bracket);
    }

    corner(const Offset(0, 0), const Offset(len, 0), const Offset(0, len));
    corner(Offset(size.width, 0), const Offset(-len, 0), const Offset(0, len));
    corner(Offset(0, size.height), const Offset(len, 0), const Offset(0, -len));
    corner(Offset(size.width, size.height), const Offset(-len, 0),
        const Offset(0, -len));
  }

  @override
  bool shouldRepaint(_BracketPainter old) => old.accent != accent;
}

class _Hairline extends StatelessWidget {
  const _Hairline();
  @override
  Widget build(BuildContext context) =>
      Container(height: 1, color: Hud.line);
}

// ── Key/value readout with dotted leader ─────────────────────────────────────

class HudReadout extends StatelessWidget {
  final String k;
  final String v;
  final Color valueColor;
  const HudReadout(this.k, this.v,
      {super.key, this.valueColor = Hud.textHi});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.baseline,
        textBaseline: TextBaseline.alphabetic,
        children: [
          HudLabel(k),
          Expanded(
            child: ClipRect(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Text(
                  '·' * 200,
                  maxLines: 1,
                  overflow: TextOverflow.clip,
                  style: const TextStyle(
                      color: Hud.textDim, fontSize: 11, fontFamily: Hud.mono),
                ),
              ),
            ),
          ),
          Flexible(
            child: Text(
              v,
              textAlign: TextAlign.right,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: valueColor,
                fontSize: 13,
                fontWeight: FontWeight.w600,
                letterSpacing: 1,
                fontFamily: Hud.mono,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ── Status LED ───────────────────────────────────────────────────────────────

class HudLed extends StatelessWidget {
  final bool on;
  final double size;
  const HudLed({super.key, required this.on, this.size = 8});

  @override
  Widget build(BuildContext context) {
    final c = on ? Hud.green : Hud.red;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: c,
        shape: BoxShape.circle,
        boxShadow: [BoxShadow(color: c.withValues(alpha: 0.6), blurRadius: 8)],
      ),
    );
  }
}

// ── Segmented gauge (battery / signal style) ─────────────────────────────────

class HudBar extends StatelessWidget {
  final double value; // 0..1
  final int segments;
  final Color color;
  const HudBar(
      {super.key,
      required this.value,
      this.segments = 12,
      this.color = Hud.amber});

  @override
  Widget build(BuildContext context) {
    final filled = (value.clamp(0.0, 1.0) * segments).round();
    return Row(
      children: List.generate(segments, (i) {
        return Expanded(
          child: Container(
            height: 10,
            margin: const EdgeInsets.symmetric(horizontal: 1),
            color: i < filled ? color : Hud.line,
          ),
        );
      }),
    );
  }
}

// ── Tactical button ──────────────────────────────────────────────────────────

class HudButton extends StatefulWidget {
  final String label;
  final IconData? icon;
  final VoidCallback onTap;
  final bool active;
  final bool danger;
  final bool expand;
  final double height;
  const HudButton({
    super.key,
    required this.label,
    required this.onTap,
    this.icon,
    this.active = false,
    this.danger = false,
    this.expand = false,
    this.height = 48,
  });

  @override
  State<HudButton> createState() => _HudButtonState();
}

class _HudButtonState extends State<HudButton> {
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    final accent = widget.danger ? Hud.red : Hud.amber;
    final filled = widget.active || widget.danger;
    final fg = filled ? Hud.bg : accent;

    return GestureDetector(
      onTapDown: (_) => setState(() => _down = true),
      onTapCancel: () => setState(() => _down = false),
      onTapUp: (_) => setState(() => _down = false),
      onTap: widget.onTap,
      child: AnimatedScale(
        scale: _down ? 0.95 : 1,
        duration: const Duration(milliseconds: 90),
        child: Container(
          height: widget.height,
          width: widget.expand ? double.infinity : null,
          padding: const EdgeInsets.symmetric(horizontal: Spacing.lg),
          decoration: BoxDecoration(
            color: filled
                ? accent
                : (_down ? Hud.panelHi : Colors.transparent),
            border: Border.all(color: accent, width: 1.2),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (widget.icon != null) ...[
                Icon(widget.icon, color: fg, size: 18),
                const SizedBox(width: Spacing.sm),
              ],
              Flexible(
                child: Text(
                  widget.label.toUpperCase(),
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: fg,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 2,
                    fontFamily: Hud.mono,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Square icon pad for the D-pad.
class HudPad extends StatefulWidget {
  final IconData icon;
  final String tag;
  final VoidCallback onTap;
  final double size;
  const HudPad(
      {super.key,
      required this.icon,
      required this.tag,
      required this.onTap,
      this.size = 72});

  @override
  State<HudPad> createState() => _HudPadState();
}

class _HudPadState extends State<HudPad> {
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTapDown: (_) => setState(() => _down = true),
      onTapCancel: () => setState(() => _down = false),
      onTapUp: (_) => setState(() => _down = false),
      onTap: widget.onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 90),
        width: widget.size,
        height: widget.size,
        decoration: BoxDecoration(
          color: _down ? Hud.amber : Hud.panel,
          border: Border.all(color: _down ? Hud.amber : Hud.lineHi, width: 1.2),
        ),
        child: Stack(
          children: [
            Center(
              child: Icon(widget.icon,
                  color: _down ? Hud.bg : Hud.amber, size: widget.size * 0.4),
            ),
            Positioned(
              left: 4,
              top: 2,
              child: Text(widget.tag,
                  style: TextStyle(
                      color: _down ? Hud.bg : Hud.textDim,
                      fontSize: 10,
                      fontFamily: Hud.mono)),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Mode selector (shared by Core + Control) ─────────────────────────────────

class HudModeSelector extends StatelessWidget {
  final List<String> modes;
  final String current;
  final ValueChanged<String> onSelect;
  const HudModeSelector(
      {super.key,
      required this.modes,
      required this.current,
      required this.onSelect});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 38,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: modes.length,
        separatorBuilder: (_, __) => const SizedBox(width: Spacing.sm),
        itemBuilder: (_, i) {
          final m = modes[i];
          return HudButton(
            label: m,
            height: 38,
            active: m == current,
            onTap: () => onSelect(m),
          );
        },
      ),
    );
  }
}

// ── Screen scaffold: bracketed title strip + LED + scroll body ───────────────

class HudScreen extends StatelessWidget {
  final String title;
  final bool connected;
  final List<Widget> children;
  const HudScreen({
    super.key,
    required this.title,
    required this.connected,
    required this.children,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
              Spacing.lg, Spacing.lg, Spacing.lg, Spacing.md),
          child: Row(
            children: [
              const RobotCarLogo(size: 26),
              const SizedBox(width: Spacing.sm),
              const Text('[',
                  style: TextStyle(
                      color: Hud.amber, fontSize: 18, fontFamily: Hud.mono)),
              const SizedBox(width: 4),
              Text(
                title.toUpperCase(),
                style: const TextStyle(
                  color: Hud.textHi,
                  fontSize: 16,
                  letterSpacing: 4,
                  fontWeight: FontWeight.w700,
                  fontFamily: Hud.mono,
                ),
              ),
              const SizedBox(width: 4),
              const Text(']',
                  style: TextStyle(
                      color: Hud.amber, fontSize: 18, fontFamily: Hud.mono)),
              const Spacer(),
              HudLed(on: connected),
              const SizedBox(width: Spacing.sm),
              HudLabel(connected ? 'LINK' : 'NO LINK',
                  color: connected ? Hud.green : Hud.red),
            ],
          ),
        ),
        Container(height: 1, color: Hud.line),
        Expanded(
          child: ListView(
            padding: EdgeInsets.fromLTRB(
              Spacing.lg,
              Spacing.lg,
              Spacing.lg,
              MediaQuery.of(context).viewPadding.bottom + Spacing.xxxl,
            ),
            children: children,
          ),
        ),
      ],
    );
  }
}

// ── Black-hole listen-orb (Core force-listen target) ─────────────────────────

class BlackHoleOrb extends StatefulWidget {
  final bool active;
  final VoidCallback onTap;
  final double size;
  const BlackHoleOrb(
      {super.key,
      required this.active,
      required this.onTap,
      required this.size});

  @override
  State<BlackHoleOrb> createState() => _BlackHoleOrbState();
}

class _BlackHoleOrbState extends State<BlackHoleOrb>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(seconds: 6))
        ..repeat();

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
          builder: (_, __) =>
              CustomPaint(painter: _BlackHolePainter(_c.value, widget.active)),
        ),
      ),
    );
  }
}

/// Spinning accretion disk wrapped around a dark event horizon with amber
/// light bleeding from inside. Amber when listening-ready, dim grey offline.
class _BlackHolePainter extends CustomPainter {
  final double t; // 0..1 rotation phase
  final bool active;
  _BlackHolePainter(this.t, this.active);

  static const _amberSoft = Color(0xFFFFC04D);

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final R = size.shortestSide / 2;
    final rect = Rect.fromCircle(center: c, radius: R);
    final tint = active ? Hud.amber : Hud.textDim;
    final soft = active ? _amberSoft : Hud.textMid;

    // ambient bloom
    canvas.drawCircle(
      c,
      R,
      Paint()
        ..shader = RadialGradient(
          colors: [tint.withValues(alpha: active ? 0.22 : 0.08), Colors.transparent],
          stops: const [0.0, 0.62],
        ).createShader(rect),
    );

    // accretion disk: a soft wide back layer + a crisp front layer, counter-spun
    void disk(double phase, double scale, double opacity, double blur) {
      final rOut = 0.88 * R * scale;
      final rIn = 0.46 * R * scale;
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = rOut - rIn
        ..shader = SweepGradient(
          colors: [
            tint.withValues(alpha: 0),
            tint.withValues(alpha: 0.05),
            tint,
            soft,
            Colors.white.withValues(alpha: active ? 0.5 : 0.15),
            tint,
            tint.withValues(alpha: 0.05),
            tint.withValues(alpha: 0),
          ],
          stops: const [0.0, 0.11, 0.33, 0.43, 0.5, 0.6, 0.84, 1.0],
          transform: GradientRotation(phase),
        ).createShader(rect);
      if (blur > 0) paint.maskFilter = MaskFilter.blur(BlurStyle.normal, blur);
      canvas.saveLayer(
          rect, Paint()..color = Colors.white.withValues(alpha: opacity));
      canvas.drawCircle(c, (rIn + rOut) / 2, paint);
      canvas.restore();
    }

    final ph = t * 2 * math.pi;
    disk(-ph * 0.6, 1.12, active ? 0.45 : 0.25, 6); // back, slow, reversed
    disk(ph, 1.0, 1.0, 0.5); // front

    // photon ring at the horizon edge
    canvas.drawCircle(
      c,
      0.42 * R,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5
        ..color = tint.withValues(alpha: active ? 0.9 : 0.4)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 2),
    );

    // event horizon: dark core with amber light from inside
    canvas.drawCircle(
      c,
      0.40 * R,
      Paint()
        ..shader = RadialGradient(
          colors: [
            tint.withValues(alpha: active ? 0.40 : 0.18),
            const Color(0xFF2A1500),
            const Color(0xFF0A0600),
            Colors.black,
          ],
          stops: const [0.0, 0.30, 0.60, 0.80],
        ).createShader(Rect.fromCircle(center: c, radius: 0.40 * R)),
    );
  }

  @override
  bool shouldRepaint(_BlackHolePainter old) =>
      old.t != t || old.active != active;
}

// ── Navigation ───────────────────────────────────────────────────────────────

class HudNavItem {
  final IconData icon;
  final String label;
  const HudNavItem({required this.icon, required this.label});
}

class HudNavBar extends StatelessWidget {
  final List<HudNavItem> items;
  final int currentIndex;
  final ValueChanged<int> onChanged;
  const HudNavBar(
      {super.key,
      required this.items,
      required this.currentIndex,
      required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Hud.bg,
        border: Border(top: BorderSide(color: Hud.line)),
      ),
      padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewPadding.bottom, top: 4),
      child: Row(
        children: List.generate(items.length, (i) {
          final sel = i == currentIndex;
          return Expanded(
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: () => onChanged(i),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(items[i].icon,
                        size: 20, color: sel ? Hud.amber : Hud.textDim),
                    const SizedBox(height: 5),
                    Text(items[i].label.toUpperCase(),
                        style: TextStyle(
                            color: sel ? Hud.amber : Hud.textDim,
                            fontSize: 9,
                            letterSpacing: 1.5,
                            fontWeight: FontWeight.w600,
                            fontFamily: Hud.mono)),
                    const SizedBox(height: 5),
                    Container(
                        height: 2,
                        width: 18,
                        color: sel ? Hud.amber : Colors.transparent),
                  ],
                ),
              ),
            ),
          );
        }),
      ),
    );
  }
}

class HudRail extends StatelessWidget {
  final List<HudNavItem> items;
  final int currentIndex;
  final ValueChanged<int> onChanged;
  const HudRail(
      {super.key,
      required this.items,
      required this.currentIndex,
      required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 84,
      decoration: const BoxDecoration(
        color: Hud.bg,
        border: Border(right: BorderSide(color: Hud.line)),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: List.generate(items.length, (i) {
          final sel = i == currentIndex;
          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => onChanged(i),
            child: Container(
              margin: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
              padding: const EdgeInsets.symmetric(vertical: 12),
              decoration: BoxDecoration(
                border: Border(
                    left: BorderSide(
                        color: sel ? Hud.amber : Colors.transparent, width: 2)),
              ),
              child: Column(
                children: [
                  Icon(items[i].icon,
                      size: 22, color: sel ? Hud.amber : Hud.textDim),
                  const SizedBox(height: 6),
                  Text(items[i].label.toUpperCase(),
                      style: TextStyle(
                          color: sel ? Hud.amber : Hud.textDim,
                          fontSize: 8,
                          letterSpacing: 1,
                          fontFamily: Hud.mono)),
                ],
              ),
            ),
          );
        }),
      ),
    );
  }
}
