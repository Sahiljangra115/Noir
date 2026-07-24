import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'config/app_config.dart';
import 'services/socket_service.dart';
import 'theme/app_theme.dart';
import 'theme/tokens.dart';
import 'utils/responsive.dart';
import 'widgets/hud.dart';

class ControlScreen extends StatelessWidget {
  const ControlScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<SocketService>(
      builder: (context, socket, child) {
        final connected = socket.isConnected;
        final currentMode = AppConfig.modes.contains(socket.state.mode)
            ? socket.state.mode
            : AppConfig.fallbackMode;
        final pad = (context.shortest * 0.18).clamp(60.0, 88.0);

        return HudScreen(
          title: 'Control',
          connected: connected,
          children: [
            HudPanel(
              label: 'MODE  ·  $currentMode',
              child: HudModeSelector(
                modes: AppConfig.modes,
                current: currentMode,
                onSelect: (m) => socket.sendCommand('mode', m),
              ),
            ),
            const SizedBox(height: Spacing.lg),

            HudPanel(
              label: 'DRIVE',
              padding: const EdgeInsets.symmetric(
                  horizontal: Spacing.lg, vertical: Spacing.xl),
              child: Center(
                child: Column(
                  children: [
                    HudPad(
                        icon: Icons.keyboard_arrow_up_rounded,
                        tag: 'F',
                        size: pad,
                        onTap: () => socket.sendCommand('move', 'F')),
                    const SizedBox(height: Spacing.sm),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        HudPad(
                            icon: Icons.keyboard_arrow_left_rounded,
                            tag: 'L',
                            size: pad,
                            onTap: () => socket.sendCommand('move', 'L')),
                        SizedBox(width: pad + Spacing.sm * 2),
                        HudPad(
                            icon: Icons.keyboard_arrow_right_rounded,
                            tag: 'R',
                            size: pad,
                            onTap: () => socket.sendCommand('move', 'R')),
                      ],
                    ),
                    const SizedBox(height: Spacing.sm),
                    HudPad(
                        icon: Icons.keyboard_arrow_down_rounded,
                        tag: 'B',
                        size: pad,
                        onTap: () => socket.sendCommand('move', 'B')),
                  ],
                ),
              ),
            ),
            const SizedBox(height: Spacing.xl),

            Semantics(
              button: true,
              label: 'Emergency stop',
              child: HudButton(
                label: 'E-STOP',
                icon: Icons.dangerous_outlined,
                danger: true,
                expand: true,
                height: 60,
                onTap: () => socket.sendCommand('move', 'S'),
              ),
            ),
            const SizedBox(height: Spacing.lg),
            Center(
              child: HudLabel(
                connected ? 'REMOTE LINK ACTIVE' : 'REMOTE LINK OFFLINE',
                color: connected ? Hud.green : Hud.red,
              ),
            ),
          ],
        );
      },
    );
  }
}
