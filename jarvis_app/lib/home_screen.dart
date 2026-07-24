import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'config/app_config.dart';
import 'services/socket_service.dart';
import 'theme/app_theme.dart';
import 'theme/tokens.dart';
import 'widgets/hud.dart';
import 'widgets/god_particle_orb.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        final state = socket.state;
        final connected = socket.isConnected;
        final currentMode = AppConfig.modes.contains(state.mode)
            ? state.mode
            : AppConfig.fallbackMode;

        return HudScreen(
          title: 'Core',
          connected: connected,
          children: [
            // Radar listen-reticle
            LayoutBuilder(
              builder: (ctx, c) {
                final dim = math
                    .min(c.maxWidth, MediaQuery.of(ctx).size.height * 0.42)
                    .clamp(200.0, 360.0);
                return Center(
                  child: Column(
                    children: [
                      Semantics(
                        button: true,
                        label: connected
                            ? 'Voice command. Tap to force-listen.'
                            : 'Voice command. Connect first.',
                        child: GodParticleOrb(
                          active: connected,
                          size: dim,
                          onTap: () {
                            if (connected) {
                              socket.forceListen();
                              return;
                            }
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content:
                                    Text('Connect to JARVIS core first.'),
                              ),
                            );
                          },
                        ),
                      ),
                      const SizedBox(height: Spacing.md),
                      HudLabel(connected ? 'TAP TO LISTEN' : 'LINK OFFLINE',
                          color: connected ? Hud.amber : Hud.red, size: 11),
                    ],
                  ),
                );
              },
            ),
            const SizedBox(height: Spacing.xl),

            // Mode selector
            HudPanel(
              label: 'MODE  ·  $currentMode',
              child: HudModeSelector(
                modes: AppConfig.modes,
                current: currentMode,
                onSelect: (m) => socket.sendCommand('mode', m),
              ),
            ),
            const SizedBox(height: Spacing.lg),

            // Transcript + AI response
            HudPanel(
              label: 'COMMS',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const HudLabel('HEARD', color: Hud.textDim),
                  const SizedBox(height: 6),
                  Text(
                    state.lastHeard.isEmpty || state.lastHeard == '...'
                        ? 'awaiting voice input'
                        : '"${state.lastHeard}"',
                    style: const TextStyle(
                      color: Hud.textHi,
                      fontSize: 15,
                      height: 1.4,
                      fontFamily: Hud.mono,
                    ),
                  ),
                  const SizedBox(height: Spacing.lg),
                  const HudLabel('JARVIS', color: Hud.textDim),
                  const SizedBox(height: 6),
                  Text(
                    state.jarvisResponse.isEmpty
                        ? 'system standby'
                        : state.jarvisResponse,
                    style: const TextStyle(
                      color: Hud.amber,
                      fontSize: 15,
                      height: 1.45,
                      fontFamily: Hud.mono,
                    ),
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}
