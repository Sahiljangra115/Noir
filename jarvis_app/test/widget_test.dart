import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:jarvis_app/main.dart';
import 'package:jarvis_app/config/app_config.dart';
import 'package:jarvis_app/services/socket_service.dart';
import 'package:jarvis_app/services/audio_service.dart';

void main() {
  testWidgets('App shell loads and shows the Core screen', (tester) async {
    final socketService = SocketService();
    final audioService = AudioService(socketService);

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: socketService),
          Provider.value(value: audioService),
        ],
        child: const JarvisApp(),
      ),
    );

    // HudScreen and HudNavBar both uppercase their labels, so "Core" shows up
    // once in the title strip and once in the nav bar. The old expectation was
    // 'C O R E', spacing from a UI revision that no longer exists.
    expect(find.text('CORE'), findsNWidgets(2));

    // The other three tabs are present but not selected.
    expect(find.text('CONTROL'), findsOneWidget);
    expect(find.text('VISION'), findsOneWidget);
    expect(find.text('SYSTEM'), findsOneWidget);
  });

  test('AppConfig modes match the backend RobotMode contract', () {
    // Guards the mismatch that used to let the app request GOTO, a mode the CV
    // loop in backend/main.py does not dispatch on: it logged "Unknown mode"
    // every frame and held the motors stopped.
    expect(AppConfig.modes,
        equals(['IDLE', 'LFR', 'HUMAN_TRACK', 'VLA', 'MANUAL']));
    expect(AppConfig.modes, contains(AppConfig.fallbackMode));
    expect(AppConfig.modes, isNot(contains('GOTO')));
  });
}
