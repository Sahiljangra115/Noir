import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../theme/app_theme.dart';
import '../theme/tokens.dart';

/// Connects to a MJPEG multipart stream from `GET /frame` and renders
/// successive JPEG frames via [Image.memory].
class MjpegStream extends StatefulWidget {
  final String url;
  final String? authToken;
  final BoxFit fit;

  const MjpegStream({
    super.key,
    required this.url,
    this.authToken,
    this.fit = BoxFit.contain,
  });

  @override
  State<MjpegStream> createState() => _MjpegStreamState();
}

class _MjpegStreamState extends State<MjpegStream> {
  Uint8List? _currentFrame;
  bool _loading = true;
  String? _error;
  StreamSubscription? _sub;
  http.Client? _client;

  @override
  void initState() {
    super.initState();
    _connect();
  }

  @override
  void didUpdateWidget(MjpegStream old) {
    super.didUpdateWidget(old);
    if (old.url != widget.url || old.authToken != widget.authToken) {
      _disconnect();
      _connect();
    }
  }

  @override
  void dispose() {
    _disconnect();
    super.dispose();
  }

  void _disconnect() {
    _sub?.cancel();
    _sub = null;
    _client?.close();
    _client = null;
  }

  Future<void> _connect() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      _client = http.Client();
      final request = http.Request('GET', Uri.parse(widget.url));
      if (widget.authToken != null && widget.authToken!.isNotEmpty) {
        request.headers['Authorization'] = 'Bearer ${widget.authToken}';
      }

      final response = await _client!.send(request);
      if (response.statusCode != 200) {
        if (mounted) {
          setState(() {
            _loading = false;
            _error = 'HTTP ${response.statusCode}';
          });
        }
        return;
      }

      // Parse multipart MJPEG boundary stream.
      // Each JPEG frame is delimited by JPEG SOI (0xFFD8) and EOI (0xFFD9)
      // markers. We accumulate bytes and extract complete frames.
      final buffer = BytesBuilder(copy: false);

      _sub = response.stream.listen(
        (chunk) {
          buffer.add(chunk);
          final bytes = buffer.toBytes();
          final frame = _extractJpeg(bytes);
          if (frame != null) {
            final endIdx = _findJpegEnd(bytes);
            buffer.clear();
            // Keep any trailing bytes after the frame
            if (endIdx != null && endIdx + 2 < bytes.length) {
              buffer.add(bytes.sublist(endIdx + 2));
            }
            if (mounted) {
              setState(() {
                _currentFrame = frame;
                _loading = false;
                _error = null;
              });
            }
          }
        },
        onError: (e) {
          if (mounted) {
            setState(() {
              _error = e.toString();
              _loading = false;
            });
          }
        },
        onDone: () {
          if (mounted) {
            setState(() {
              _error = 'Stream ended';
              _loading = false;
            });
          }
        },
        cancelOnError: false,
      );
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e.toString();
        });
      }
    }
  }

  /// Find start-of-image (0xFFD8) index in [bytes].
  int? _findJpegStart(Uint8List bytes) {
    for (var i = 0; i < bytes.length - 1; i++) {
      if (bytes[i] == 0xFF && bytes[i + 1] == 0xD8) return i;
    }
    return null;
  }

  /// Find end-of-image (0xFFD9) index in [bytes].
  int? _findJpegEnd(Uint8List bytes) {
    for (var i = bytes.length - 2; i >= 0; i--) {
      if (bytes[i] == 0xFF && bytes[i + 1] == 0xD9) return i;
    }
    return null;
  }

  /// Extract a complete JPEG frame from [bytes], or null if none found.
  Uint8List? _extractJpeg(Uint8List bytes) {
    final start = _findJpegStart(bytes);
    final end = _findJpegEnd(bytes);
    if (start != null && end != null && end > start) {
      return Uint8List.fromList(bytes.sublist(start, end + 2));
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _currentFrame == null) {
      return const Center(
        child: SizedBox(
          width: 28,
          height: 28,
          child: CircularProgressIndicator(strokeWidth: 2, color: Hud.amber),
        ),
      );
    }

    if (_error != null && _currentFrame == null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.videocam_off_outlined,
              color: Hud.textDim,
              size: 36,
            ),
            const SizedBox(height: Spacing.sm),
            Text(
              _error!,
              style: const TextStyle(
                color: Hud.textDim,
                fontSize: 11,
                fontFamily: Hud.mono,
              ),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      );
    }

    if (_currentFrame != null) {
      return Image.memory(
        _currentFrame!,
        fit: widget.fit,
        gaplessPlayback: true,
      );
    }

    return const SizedBox.shrink();
  }
}
