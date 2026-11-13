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
