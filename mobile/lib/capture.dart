import 'dart:async';
import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'capture_quality.dart';
import 'documents.dart';
import 'selection.dart';

class CaptureScreen extends StatefulWidget {
  const CaptureScreen({
    super.key,
    this.count = 0,
    this.onPhoto,
    this.recordMode = false,
  });
  final int count;
  final Future<void> Function(String path)? onPhoto;
  final bool recordMode;
  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen>
    with WidgetsBindingObserver {
  CameraController? camera;
  String? error;
  bool saving = false, recording = false;
  int added = 0, seconds = 0;
  Timer? timer;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    initialize();
  }

  Future<void> initialize() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        throw StateError('No camera is available. Import images instead.');
      }
      final selected = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );
      final controller = await _openController(selected);
      if (!mounted) {
        await controller.dispose();
        return;
      }
      if (!widget.recordMode) {
        try {
          await controller.setJpegImageQuality(95);
        } catch (e) {
          // Some devices/camera versions reject a quality change; the capture
          // still works, so keep the controller rather than failing the screen.
          debugPrint('JPEG quality change unavailable: $e');
        }
      }
      camera = controller;
      setState(() => error = null);
    } catch (e) {
      if (mounted) setState(() => error = 'Camera unavailable: $e');
    }
  }

  Future<CameraController> _openController(CameraDescription selected) async {
    // Phase 0 interim fix: photos must not inherit the 720p video preset.
    // Fall back rather than making the camera unusable if `max` is rejected.
    final presets = widget.recordMode
        ? const [ResolutionPreset.high]
        : const [
            ResolutionPreset.max,
            ResolutionPreset.veryHigh,
            ResolutionPreset.high,
          ];
    Object? lastError;
    for (final preset in presets) {
      final controller = CameraController(selected, preset, enableAudio: false);
      try {
        await controller.initialize();
        return controller;
      } on CameraException catch (e) {
        await controller.dispose();
        if (e.code == 'CameraAccessDenied' ||
            e.code == 'CameraAccessDeniedWithoutPrompt') {
          rethrow;
        }
        lastError = e;
        debugPrint('Camera preset $preset unavailable: $e');
      } catch (e) {
        await controller.dispose();
        lastError = e;
        debugPrint('Camera preset $preset unavailable: $e');
      }
    }
    throw lastError ?? StateError('Camera could not start.');
  }

  /// Capture once, validate the JPEG cheaply, and retry once if the camera
  /// returned a black/empty frame. Returns the path to import.
  Future<String> _validatedPhotoPath() async {
    var photo = await camera!.takePicture();
    var info = await _readInfo(photo.path);
    if (info != null && !info.isUsable) {
      debugPrint('Discarding unusable capture: ${info.summary}');
      try {
        await File(photo.path).delete();
      } catch (_) {}
      photo = await camera!.takePicture();
      info = await _readInfo(photo.path);
      if (info != null && !info.isUsable) {
        throw StateError('The camera returned an unreadable photo. Try again.');
      }
    }
    if (info != null) {
      debugPrint(
        'Capture ${info.summary}${info.isLowResolution ? ' (low resolution)' : ''}',
      );
    }
    return photo.path;
  }

  Future<CaptureInfo?> _readInfo(String path) async {
    try {
      return await readCaptureInfo(path);
    } catch (e) {
      // Validation is a safety net, not a reason to lose a capture.
      debugPrint('Could not validate capture: $e');
      return null;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive) {
      timer?.cancel();
      if (recording) {
        finishVideo();
      } else {
        camera?.dispose();
        camera = null;
      }
    } else if (state == AppLifecycleState.resumed && camera == null) {
      initialize();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    camera?.dispose();
    super.dispose();
  }

  Future<void> finishVideo() async {
    if (saving || !recording || camera == null) return;
    timer?.cancel();
    setState(() => saving = true);
    try {
      final video = await camera!.stopVideoRecording();
      if (mounted) Navigator.pop(context, video.path);
    } catch (e) {
      if (mounted) {
        setState(() {
          error = 'Recording could not be saved: $e';
          saving = false;
          recording = false;
        });
      }
    }
  }

  Future<void> shutter() async {
    if (saving || camera?.value.isInitialized != true) return;
    if (widget.recordMode) {
      if (recording) {
        await finishVideo();
        return;
      }
      try {
        await camera!.startVideoRecording();
        if (!mounted) return;
        setState(() {
          recording = true;
          seconds = 0;
        });
        timer = Timer.periodic(const Duration(seconds: 1), (_) {
          if (!mounted) return;
          setState(() => seconds++);
          if (seconds >= 600) finishVideo();
        });
      } catch (e) {
        if (mounted) setState(() => error = e.toString());
      }
      return;
    }
    setState(() => saving = true);
    try {
      final path = await _validatedPhotoPath();
      await widget.onPhoto!(path);
      if (mounted) setState(() => added++);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(e.toString())));
      }
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !saving && !recording,
    child: Scaffold(
      appBar: AppBar(
        title: Text(widget.recordMode ? 'Record a book' : 'Capture pages'),
        actions: [
          if (!widget.recordMode)
            TextButton(
              onPressed: saving ? null : () => Navigator.pop(context),
              child: Text('Done (${widget.count + added})'),
            ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: error != null
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Text(error!),
                      ),
                    )
                  : camera?.value.isInitialized == true
                  ? Center(child: CameraPreview(camera!))
                  : const Center(child: CircularProgressIndicator()),
            ),
            Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                children: [
                  Text(
                    widget.recordMode
                        ? (recording
                              ? '${seconds ~/ 60}:${(seconds % 60).toString().padLeft(2, '0')} / 10:00'
                              : 'Hold each spread still for at least one second.\nTurn pages slowly. Video is recorded without sound.')
                        : 'Take all your photos first. Review them after Done.',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    height: 64,
                    width: 180,
                    child: FilledButton.icon(
                      onPressed:
                          saving ||
                              camera?.value.isInitialized != true ||
                              (!widget.recordMode &&
                                  widget.count + added >= 150)
                          ? null
                          : shutter,
                      icon: Icon(
                        recording
                            ? Icons.stop
                            : widget.recordMode
                            ? Icons.videocam
                            : Icons.camera_alt,
                      ),
                      label: Text(
                        saving
                            ? 'Saving…'
                            : recording
                            ? 'Stop & review'
                            : widget.recordMode
                            ? 'Record'
                            : 'Capture',
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class VideoOptionsSheet extends StatefulWidget {
  const VideoOptionsSheet({super.key});
  @override
  State<VideoOptionsSheet> createState() => _VideoOptionsSheetState();
}

class _VideoOptionsSheetState extends State<VideoOptionsSheet> {
  String layout = 'spread';
  @override
  Widget build(BuildContext context) => SafeArea(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Video → book',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 12),
          const Text(
            'Experimental. Review every extracted page for missing pages, duplicates and crop errors before export.',
          ),
          const SizedBox(height: 20),
          DropdownButtonFormField<String>(
            isExpanded: true,
            initialValue: layout,
            decoration: const InputDecoration(labelText: 'Page layout'),
            items:
                {
                      'spread': 'Open book · left page then right',
                      'single': 'One page at a time',
                      'auto': 'Detect layout automatically',
                    }.entries
                    .map(
                      (entry) => DropdownMenuItem(
                        value: entry.key,
                        child: SelectionLabel(
                          entry.value,
                          selected: entry.key == layout,
                        ),
                      ),
                    )
                    .toList(),
            onChanged: (v) => setState(() => layout = v!),
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: () => Navigator.pop(context, ('record', layout)),
            icon: const Icon(Icons.videocam_outlined),
            label: const Text('Record a book'),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () => Navigator.pop(context, ('import', layout)),
            icon: const Icon(Icons.video_library_outlined),
            label: const Text('Import a video'),
          ),
        ],
      ),
    ),
  );
}
