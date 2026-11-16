/// Cheap metadata for a just-captured photo. The native side decodes only a
/// small sample, so this is safe to run between captures.
class CaptureInfo {
  const CaptureInfo({
    required this.path,
    required this.width,
    required this.height,
    required this.bytes,
    required this.meanLuma,
    required this.darkFraction,
    required this.brightFraction,
  });

  final String path;
  final int width;
  final int height;
  final int bytes;
  final double meanLuma;
  final double darkFraction;
  final double brightFraction;

  int get pixels => width * height;

  /// Reject only a clearly black/empty frame. A legitimately dark photo should
  /// still be importable; the quality gate is a later phase.
  bool get isProbablyBlack =>
      meanLuma < 2 || (darkFraction > 0.999 && brightFraction < 0.001);

  bool get isLowResolution => width <= 0 || height <= 0 || pixels < 1000000;

  bool get isUsable =>
      bytes > 1024 && width > 0 && height > 0 && !isProbablyBlack;

  String get summary {
    final megabytes = bytes / (1024 * 1024);
    return '${width}x$height, ${megabytes.toStringAsFixed(1)} MB, '
        'mean luma ${meanLuma.toStringAsFixed(0)}';
  }

  factory CaptureInfo.fromMap(Map<String, dynamic> map) => CaptureInfo(
    path: map['path'] as String? ?? '',
    width: _int(map['width']),
    height: _int(map['height']),
    bytes: _int(map['bytes']),
    meanLuma: _double(map['meanLuma']),
    darkFraction: _double(map['darkFraction']),
    brightFraction: _double(map['brightFraction']),
  );

  static int _int(Object? value) => (value as num?)?.toInt() ?? 0;
  static double _double(Object? value) => (value as num?)?.toDouble() ?? 0;
}

/// Blur and glare measured natively on a just-captured photo
/// (docs/TECH_UPGRADE_PLAN.md C3; reference: evals/harness/eval_capture_quality.py).
/// Advisory: the user is offered a retake and may keep the photo.
class CaptureQuality {
  const CaptureQuality({
    required this.sharpness,
    required this.lapVar,
    required this.glare,
  });

  /// Thresholds chosen on DocUNet documents 1-32; on documents 33-65 they
  /// catch 100% of out-of-focus, 91% of shaken and 100% of glare-damaged
  /// photos, and warn on 6% of usable ones (those read worse: CER 0.69 vs 0.46).
  static const blurSharpness = 0.40;
  static const blurLapVar = 250.0;
  static const glareFraction = 0.03;

  final double sharpness;
  final double lapVar;
  final double glare;

  bool get blurry => sharpness < blurSharpness || lapVar < blurLapVar;
  bool get hasGlare => glare >= glareFraction;
  bool get ok => !blurry && !hasGlare;

  /// One plain sentence for the retake prompt, or null when the photo is fine.
  String? get problem {
    if (blurry && hasGlare) {
      return 'This photo looks blurry and has a bright glare patch. Text in it may be misread.';
    }
    if (blurry) {
      return 'This photo looks blurry. Text in it may be misread.';
    }
    if (hasGlare) {
      return 'This photo has a bright glare patch. Text under it may be lost.';
    }
    return null;
  }

  factory CaptureQuality.fromMap(Map<String, dynamic> map) => CaptureQuality(
    sharpness: CaptureInfo._double(map['sharpness']),
    lapVar: CaptureInfo._double(map['lapvar']),
    glare: CaptureInfo._double(map['glare']),
  );
}
