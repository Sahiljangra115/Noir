import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:socket_io_client/socket_io_client.dart' as IO;
import 'package:record/record.dart';
import 'package:just_audio/just_audio.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sensors_plus/sensors_plus.dart';
import 'package:geolocator/geolocator.dart';
import 'dart:async';
import 'dart:math';
import 'dart:typed_data';

class HomeScreen extends StatefulWidget {
  const HomeScreen({Key? key}) : super(key: key);

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with SingleTickerProviderStateMixin {
  IO.Socket? socket;
  final AudioRecorder _audioRecorder = AudioRecorder();
  final AudioPlayer _audioPlayer = AudioPlayer();
  
  bool _isConnected = false;
  String _lastHeard = "...";
  String _jarvisResponse = "Online and ready.";
  
  // Sensor mock/data
  String _imuData = "X: 0.0 Y: 0.0 Z: 0.0";
  String _gpsData = "Lat: 0.0 Lon: 0.0";

  late AnimationController _rotationController;
  StreamSubscription<AccelerometerEvent>? _accelerometerSubscription;
  StreamSubscription<Position>? _positionStreamSubscription;

  @override
  void initState() {
    super.initState();
    _rotationController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 10),
    )..repeat();

    _initConnection();
    _initSensors();
  }

  Future<void> _initSensors() async {
    _accelerometerSubscription = accelerometerEventStream().listen((AccelerometerEvent event) {
      if (mounted) {
        setState(() {
          _imuData = "X: ${event.x.toStringAsFixed(1)} Y: ${event.y.toStringAsFixed(1)} Z: ${event.z.toStringAsFixed(1)}";
        });
        if (_isConnected && socket != null) {
          // You could optionally transmit telemetry to JARVIS here
        }
      }
    });

    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (serviceEnabled) {
      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.whileInUse || permission == LocationPermission.always) {
        _positionStreamSubscription = Geolocator.getPositionStream().listen((Position position) {
          if (mounted) {
            setState(() {
              _gpsData = "Lat: ${position.latitude.toStringAsFixed(4)} Lon: ${position.longitude.toStringAsFixed(4)}";
            });
            if (_isConnected && socket != null) {
              // You could optionally transmit GPS telemetry
            }
          }
        });
      }
    }
  }

  Future<void> _initConnection() async {
    final prefs = await SharedPreferences.getInstance();
    final ip = prefs.getString('laptop_ip') ?? '192.168.1.100';
    final port = prefs.getString('laptop_port') ?? '5000';

    final url = 'http://$ip:$port';
    print("Connecting to $url...");

    socket = IO.io(url, IO.OptionBuilder()
        .setTransports(['websocket'])
        .enableAutoConnect()
        .build());

    socket?.onConnect((_) {
      print('Connected to JARVIS core');
      setState(() => _isConnected = true);
      _startAudioStream();
    });

    socket?.onDisconnect((_) {
      print('Disconnected from JARVIS core');
      setState(() => _isConnected = false);
      _stopAudioStream();
    });

    socket?.on('state_update', (data) {
      if (data != null && data is Map) {
        setState(() {
          if (data['last_heard'] != null) _lastHeard = data['last_heard'];
          if (data['jarvis_response'] != null) _jarvisResponse = data['jarvis_response'];
        });
      }
    });

    socket?.on('tts_audio', (data) {
      _playTtsAudio(data);
    });
  }
  
  Future<void> _playTtsAudio(dynamic data) async {
    if (data is List<dynamic>) {
       List<int> intList = data.cast<int>();
       try {
         await _audioPlayer.setAudioSource(MyCustomSource(intList));
         _audioPlayer.play();
       } catch (e) {
         print("Error playing audio: $e");
       }
    }
  }

  Future<void> _startAudioStream() async {
    if (await _audioRecorder.hasPermission()) {
      final stream = await _audioRecorder.startStream(const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 16000,
        numChannels: 1,
      ));

      stream.listen((data) {
        if (_isConnected) {
          socket?.emit('audio_stream', data);
        }
      });
    }
  }

  Future<void> _stopAudioStream() async {
    await _audioRecorder.stop();
  }

  void _triggerJarvis() {
    print("Force listen triggered");
    socket?.emit('force_listen', {});
  }

  @override
  void dispose() {
    _accelerometerSubscription?.cancel();
    _positionStreamSubscription?.cancel();
    _rotationController.dispose();
    _audioRecorder.dispose();
    _audioPlayer.dispose();
    socket?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        title: const Text('J A R V I S'),
        actions: [
          IconButton(
            icon: Icon(
              Icons.radio_button_checked,
              size: 18,
              color: _isConnected ? const Color(0xFF00E5FF) : Colors.redAccent,
            ),
            onPressed: () {},
          ),
          IconButton(
            icon: const Icon(Icons.tune, size: 20),
            onPressed: () async {
              final reconnect = await Navigator.pushNamed(context, '/settings');
              if (reconnect == true) {
                 socket?.dispose();
                 _initConnection();
              }
            },
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Stack(
        children: [
          // Subtle background gradient
          Container(
            decoration: const BoxDecoration(
              gradient: RadialGradient(
                colors: [Color(0xFF101A24), Color(0xFF030507)],
                center: Alignment.center,
                radius: 1.5,
              ),
            ),
          ),
          SafeArea(
            child: Column(
              children: [
                const Spacer(flex: 1),
                // Holographic Orb
                GestureDetector(
                  onTap: _triggerJarvis,
                  child: AnimatedBuilder(
                    animation: _rotationController,
                    builder: (context, child) {
                      return CustomPaint(
                        painter: HolographicOrbPainter(_rotationController.value, _isConnected),
                        size: const Size(220, 220),
                      );
                    },
                  ),
                ),
                const Spacer(flex: 1),
                
                // CONVERSATION LOG IN GLASS PANEL
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24.0),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(24),
                    child: BackdropFilter(
                      filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
                      child: Container(
                        padding: const EdgeInsets.all(24),
                        decoration: BoxDecoration(
                          color: Colors.white.withOpacity(0.03),
                          borderRadius: BorderRadius.circular(24),
                          border: Border.all(color: Colors.white.withOpacity(0.05)),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                             Text(
                               "TRANSCRIPT", 
                               style: TextStyle(color: Colors.white.withOpacity(0.4), fontSize: 10, fontWeight: FontWeight.w300, letterSpacing: 2)
                             ),
                             const SizedBox(height: 8),
                             Text(
                               '"$_lastHeard"', 
                               style: TextStyle(fontSize: 18, fontWeight: FontWeight.w200, color: Colors.white.withOpacity(0.8), fontStyle: FontStyle.italic)
                             ),
                             const SizedBox(height: 24),
                             Text(
                               "AI RESPONSE", 
                               style: TextStyle(color: const Color(0xFF00E5FF).withOpacity(0.6), fontSize: 10, fontWeight: FontWeight.w300, letterSpacing: 2)
                             ),
                             const SizedBox(height: 8),
                             Text(
                               _jarvisResponse, 
                               style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w300, color: Colors.white)
                             ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                
                const SizedBox(height: 32),
                
                // SENSOR PANEL
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 24.0),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      _buildSensorWidget("SYSTEM IMU", _imuData),
                      _buildSensorWidget("TELEMETRY", _gpsData),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSensorWidget(String title, String data) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title, 
          style: TextStyle(color: Colors.white.withOpacity(0.3), fontSize: 9, fontWeight: FontWeight.w400, letterSpacing: 2)
        ),
        const SizedBox(height: 6),
        Text(
          data, 
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w200, color: Colors.white70, letterSpacing: 1)
        ),
      ],
    );
  }
}

class HolographicOrbPainter extends CustomPainter {
  final double rotation;
  final bool isConnected;
  HolographicOrbPainter(this.rotation, this.isConnected);

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final coreColor = isConnected ? const Color(0xFF00E5FF) : Colors.white24;
    
    // Ambient Glow
    final glowPaint = Paint()
      ..color = coreColor.withOpacity(0.15)
      ..style = PaintingStyle.fill
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 30.0);
    canvas.drawCircle(center, size.width / 2.5, glowPaint);

    // Orbiting fine lines
    final outerRing = Paint()
      ..color = Colors.white.withOpacity(0.1)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.5;
    
    canvas.save();
    canvas.translate(center.dx, center.dy);
    canvas.rotate(rotation * 2 * pi);
    canvas.drawOval(Rect.fromCenter(center: Offset.zero, width: size.width * 0.9, height: size.width * 0.9), outerRing);
    
    // Rotating arc marker
    final arcPaint = Paint()
      ..color = coreColor.withOpacity(0.6)
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = 1.5;
    canvas.drawArc(
      Rect.fromCenter(center: Offset.zero, width: size.width * 0.9, height: size.width * 0.9),
      0, pi / 3, false, arcPaint
    );
    canvas.restore();

    // Inner wave structure
    canvas.save();
    canvas.translate(center.dx, center.dy);
    canvas.rotate(-rotation * 4 * pi); // reverse sync
    final innerRing = Paint()
      ..color = coreColor.withOpacity(0.3)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;
    
    for (int i = 0; i < 3; i++) {
       canvas.rotate(pi / 3);
       canvas.drawOval(Rect.fromCenter(center: Offset.zero, width: size.width * 0.6, height: size.width * 0.2), innerRing);
    }
    canvas.restore();

    // Solid core
    final core = Paint()
      ..color = coreColor.withOpacity(0.9)
      ..style = PaintingStyle.fill
      ..maskFilter = const MaskFilter.blur(BlurStyle.solid, 4.0);
    canvas.drawCircle(center, 4.0, core);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}

class MyCustomSource extends StreamAudioSource {
  final List<int> bytes;
  MyCustomSource(this.bytes);

  @override
  Future<StreamAudioResponse> request([int? start, int? end]) async {
    start ??= 0;
    end ??= bytes.length;
    return StreamAudioResponse(
      sourceLength: bytes.length,
      contentLength: end - start,
      offset: start,
      stream: Stream.value(bytes.sublist(start, end)),
      contentType: 'audio/wav',
    );
  }
}