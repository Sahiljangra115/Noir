import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:jarvis_app/main.dart';
import 'package:jarvis_app/services/socket_service.dart';
import 'package:jarvis_app/services/audio_service.dart';

void main() {
  testWidgets('App basic load test', (WidgetTester tester) async {
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

    // Verify that our app shows the C O R E title in the app bar.
    expect(find.text('C O R E'), findsOneWidget);
    
    // Check for the Core tab in bottom navigation.
    expect(find.text('CORE'), findsOneWidget);
  });
}
