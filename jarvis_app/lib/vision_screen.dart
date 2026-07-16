import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'services/socket_service.dart';
import 'theme/app_theme.dart';
import 'theme/tokens.dart';
import 'widgets/hud.dart';
import 'widgets/mjpeg_stream.dart';

class VisionScreen extends StatelessWidget {
  const VisionScreen({super.key});

  double _num(dynamic v) => v is num ? v.toDouble() : 0.0;

  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        final state = socket.state;
        final connected = socket.isConnected;
        final accel = state.imu['accel'] is Map
            ? Map<String, dynamic>.from(state.imu['accel'])
            : {'x': 0.0, 'y': 0.0, 'z': 0.0};
        final ax = _num(accel['x']);
        final ay = _num(accel['y']);
        final az = _num(accel['z']);
        final lat = _num(state.gps['lat']);
        final lon = _num(state.gps['lon']);

        return HudScreen(
          title: 'Vision',
          connected: connected,
          children: [
            const HudLabel('OPTICAL FEED'),
            const SizedBox(height: Spacing.sm),
            Container(
              decoration: BoxDecoration(border: Border.all(color: Hud.lineHi)),
              child: AspectRatio(
                aspectRatio: 16 / 9,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    Container(
                      color: Colors.black,
                      child: connected
                          ? MjpegStream(
                              url: '${socket.host}/frame',
                              authToken: socket.token,
                              fit: BoxFit.cover,
                            )
                          : const Center(
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(Icons.videocam_off_outlined,
                                      color: Hud.textDim, size: 40),
                                  SizedBox(height: Spacing.sm),
                                  HudLabel('NO SIGNAL', color: Hud.textDim),
                                ],
                              ),
                            ),
                    ),
                    // HUD overlay: crosshair + corner ticks
                    IgnorePointer(
                      child: CustomPaint(
                        painter: _FeedOverlay(connected),
                        size: Size.infinite,
                      ),
                    ),
                    Positioned(
                      left: 8,
                      top: 8,
                      child: Row(
                        children: [
                          HudLed(on: connected, size: 7),
                          const SizedBox(width: 6),
                          HudLabel(connected ? 'LIVE' : 'OFFLINE',
                              color: connected ? Hud.green : Hud.red, size: 9),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: Spacing.lg),

            HudPanel(
              label: 'TELEMETRY',
              child: Column(
                children: [
                  HudReadout('IMU·X', ax.toStringAsFixed(2)),
                  HudReadout('IMU·Y', ay.toStringAsFixed(2)),
                  HudReadout('IMU·Z', az.toStringAsFixed(2)),
                  const SizedBox(height: 6),
                  HudReadout('GPS·LAT', lat.toStringAsFixed(5)),
                  HudReadout('GPS·LON', lon.toStringAsFixed(5)),
                  const SizedBox(height: 6),
                  HudReadout('MODE', state.mode, valueColor: Hud.amber),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}

class _FeedOverlay extends CustomPainter {
  final bool active;
  const _FeedOverlay(this.active);

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final p = Paint()
      ..color = (active ? Hud.amber : Hud.textDim).withValues(alpha: 0.5)
      ..strokeWidth = 1;
    // center reticle
    canvas.drawLine(Offset(c.dx - 12, c.dy), Offset(c.dx - 4, c.dy), p);
    canvas.drawLine(Offset(c.dx + 4, c.dy), Offset(c.dx + 12, c.dy), p);
    canvas.drawLine(Offset(c.dx, c.dy - 12), Offset(c.dx, c.dy - 4), p);
    canvas.drawLine(Offset(c.dx, c.dy + 4), Offset(c.dx, c.dy + 12), p);
    // corner ticks
    const m = 8.0, len = 14.0;
    for (final corner in [
      [const Offset(m, m), const Offset(len, 0), const Offset(0, len)],
      [Offset(size.width - m, m), const Offset(-len, 0), const Offset(0, len)],
      [Offset(m, size.height - m), const Offset(len, 0), const Offset(0, -len)],
      [
        Offset(size.width - m, size.height - m),
        const Offset(-len, 0),
        const Offset(0, -len)
      ],
    ]) {
      canvas.drawLine(corner[0], corner[0] + corner[1], p);
      canvas.drawLine(corner[0], corner[0] + corner[2], p);
    }
  }

  @override
  bool shouldRepaint(_FeedOverlay old) => old.active != active;
}
