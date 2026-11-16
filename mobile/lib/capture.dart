import 'dart:async';
import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'capture_quality.dart';
import 'documents.dart';
import 'selection.dart';
import 'errors.dart';

/// Offers a retake when a capture looks blurry or has glare (C3). Returns
/// true to keep the photo: always when it looks fine or could not be checked,
/// and when the prompt is closed without a choice (never lose a capture).
Future<bool> keepAfterQualityCheck(
  BuildContext context,
  CaptureQuality? quality,
) async {
  final problem = quality?.problem;
  if (problem == null) return true;
  final retake = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Retake this page?'),
      content: Text(problem),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: const Text('Keep photo'),
        ),
        FilledButton(
          autofocus: true,
          onPressed: () => Navigator.pop(context, true),
          child: const Text('Retake'),
        ),
      ],
    ),
  );
  return retake != true;
}

/// What to do when a new photo looks like the previous one (C4).
enum SamePageChoice { keepSharper, keepBoth }

/// Asks whether a photo that looks like the previous one is the same page
/// again. [newIsSharper] says which of the two the C3 sharpness prefers.
/// Closing the prompt keeps both: never lose a capture.
Future<SamePageChoice> askSamePage(
  BuildContext context, {
  required bool newIsSharper,
}) async {
  final choice = await showDialog<SamePageChoice>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Same page again?'),
      content: Text(
        newIsSharper
            ? 'This photo looks like the previous one, and it is sharper. '
                  'Keep only this one?'
            : 'This photo looks like the previous one, which is sharper. '
                  'Keep only the previous one?',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, SamePageChoice.keepBoth),
          child: const Text('Keep both'),
        ),
        // No default focus: a different page can look alike (3% of
        // different documents in the evaluation), so replacing is a
        // deliberate tap.
        FilledButton(
          onPressed: () => Navigator.pop(context, SamePageChoice.keepSharper),
          child: const Text('Keep the sharper one'),
        ),
      ],
    ),
  );
  return choice ?? SamePageChoice.keepBoth;
}

/// Removes a page that [CaptureScreen.onPhoto] added (C4: a sharper shot of
/// the same page replaces it).
typedef RemovePhoto = Future<void> Function();

class CaptureScreen extends StatefulWidget {
  const CaptureScreen({
    super.key,
    this.count = 0,
    this.onPhoto,
    this.recordMode = false,
  });
  final int count;

  /// Adds the photo; may return a way to remove it again.
  final Future<RemovePhoto?> Function(String path)? onPhoto;
  final bool recordMode;
  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen>
    with WidgetsBindingObserver {
  CameraController? camera;
  String? error;
  bool saving = false, recording = false;
  // The last kept photo of this batch (C4): fingerprint, sharpness, removal.
  String? lastHash;
  double? lastSharpness;
  RemovePhoto? removeLast;
  // C3 "page cut off" runs while the next page is framed; the next shot
  // waits for it (the native worker does one job at a time).
  Future<void> pendingCut = Future.value();
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
      if (mounted) {
        setState(
          () => error = friendlyError(
            e,
            'The camera could not start. Close other camera apps and try '
            'again, or import images instead.',
          ),
        );
      }
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

  Future<CaptureQuality?> _readQuality(String path) async {
    try {
      return await readCaptureQuality(path);
    } catch (e) {
      // Like validation, the check never costs the user a capture.
      debugPrint('Could not check capture quality: $e');
      return null;
    }
  }

  /// Offers a retake when text runs off an edge of the photo (C3). Advisory,
  /// and never blocks: a failed check says nothing.
  Future<void> _checkCut(String path, RemovePhoto? removal, int number) async {
    try {
      final sides = await readCutOff(path);
      const fine = CaptureQuality(sharpness: 1, lapVar: 1e9, glare: 0);
      if (!fine.withCutOff(sides).cutOff || !mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          duration: const Duration(seconds: 8),
          content: Text(
            'Photo $number: part of the page seems to be outside the photo.',
          ),
          action: removal == null
              ? null
              : SnackBarAction(
                  label: 'Retake',
                  onPressed: () async {
                    await removal();
                    if (removeLast == removal) {
                      removeLast = null;
                      lastHash = null;
                      lastSharpness = null;
                    }
                    if (mounted) setState(() => added--);
                  },
                ),
        ),
      );
    } catch (e) {
      debugPrint('Could not check for a cut-off page: $e');
    }
  }

  Future<String?> _readHash(String path) async {
    try {
      return await readPageFingerprint(path);
    } catch (e) {
      debugPrint('Could not fingerprint capture: $e');
      return null;
    }
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
          error = friendlyError(
            e,
            'The recording could not be saved. Check free storage, then try again.',
          );
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
        unawaited(HapticFeedback.mediumImpact());
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
        if (mounted) {
          setState(
            () => error = friendlyError(
              e,
              'Recording could not start. Try again.',
            ),
          );
        }
      }
      return;
    }
    setState(() => saving = true);
    try {
      await pendingCut;
      final path = await _validatedPhotoPath();
      // C3: blur and glare are advisory. Retake discards this photo; Keep
      // (or closing the prompt) adds it as it is.
      final quality = await _readQuality(path);
      if (mounted && !await keepAfterQualityCheck(context, quality)) {
        try {
          await File(path).delete();
        } catch (_) {}
        return;
      }
      // C4: the same page shot twice keeps the sharper photo (if asked).
      final hash = await _readHash(path);
      final sharpness = quality?.sharpness;
      var replaced = false;
      if (mounted &&
          samePage(lastHash, hash) &&
          sharpness != null &&
          lastSharpness != null) {
        final newIsSharper = sharpness >= lastSharpness!;
        final choice = await askSamePage(context, newIsSharper: newIsSharper);
        if (choice == SamePageChoice.keepSharper) {
          if (!newIsSharper) {
            try {
              await File(path).delete();
            } catch (_) {}
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Kept the previous, sharper photo.'),
                ),
              );
            }
            return;
          }
          final remove = removeLast;
          if (remove != null) {
            await remove();
            replaced = true;
          }
        }
      }
      final removal = await widget.onPhoto!(path);
      pendingCut = _checkCut(
        path,
        removal,
        widget.count + added + (replaced ? 0 : 1),
      );
      lastHash = hash;
      lastSharpness = sharpness;
      removeLast = removal;
      if (mounted) {
        unawaited(HapticFeedback.mediumImpact());
        if (!replaced) setState(() => added++);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              friendlyError(e, 'This photo could not be saved. Try again.'),
            ),
          ),
        );
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
                  // Announced as it changes: recording start, elapsed time
                  // and the photo count are otherwise silent for TalkBack.
                  Semantics(
                    liveRegion: true,
                    child: Text(
                      widget.recordMode
                          ? (recording
                                ? '${seconds ~/ 60}:${(seconds % 60).toString().padLeft(2, '0')} / 10:00'
                                : 'Hold each spread still for at least one second.\nTurn pages slowly. Video is recorded without sound.')
                          : added == 0
                          ? 'Take all your photos first. Review them after Done.'
                          : '${widget.count + added} ${widget.count + added == 1 ? 'photo' : 'photos'} taken. Review them after Done.',
                      textAlign: TextAlign.center,
                    ),
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
  bool fingers = false;
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
          // F3: off by default (pictures printed to a page edge can be
          // blanked too); ink is never changed.
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Remove fingers at page edges'),
            subtitle: const Text(
              'Blanks thumbs and fingers holding the book. Text is never changed; pictures at the page edge can be blanked too.',
            ),
            value: fingers,
            onChanged: (v) => setState(() => fingers = v),
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: () => Navigator.pop(context, ('record', layout, fingers)),
            icon: const Icon(Icons.videocam_outlined),
            label: const Text('Record a book'),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () => Navigator.pop(context, ('import', layout, fingers)),
            icon: const Icon(Icons.video_library_outlined),
            label: const Text('Import a video'),
          ),
        ],
      ),
    ),
  );
}
