import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/capture_quality.dart';

void main() {
  CaptureInfo info({
    int width = 4000,
    int height = 3000,
    int bytes = 4 * 1024 * 1024,
    double meanLuma = 205,
    double darkFraction = 0.02,
    double brightFraction = 0.01,
  }) => CaptureInfo(
    path: '/tmp/photo.jpg',
    width: width,
    height: height,
    bytes: bytes,
    meanLuma: meanLuma,
    darkFraction: darkFraction,
    brightFraction: brightFraction,
  );

  test('accepts a normal high-resolution page', () {
    final capture = info();
    expect(capture.isUsable, isTrue);
    expect(capture.isLowResolution, isFalse);
    expect(capture.summary, contains('4000x3000'));
  });

  test('rejects a black frame', () {
    final capture = info(meanLuma: 0.5, darkFraction: 0.9995);
    expect(capture.isProbablyBlack, isTrue);
    expect(capture.isUsable, isFalse);
  });

  test('rejects a truncated file', () {
    expect(info(bytes: 500).isUsable, isFalse);
  });

  test('accepts a low-resolution capture but flags it', () {
    final capture = info(width: 1280, height: 720);
    expect(capture.isUsable, isTrue);
    expect(capture.isLowResolution, isTrue);
  });

  test('parses native metadata defensively', () {
    final capture = CaptureInfo.fromMap({
      'width': 4032,
      'height': 3024,
      'bytes': 3500000,
      'meanLuma': 198.4,
      'darkFraction': 0.04,
      'brightFraction': 0.02,
    });
    expect(capture.path, isEmpty);
    expect(capture.pixels, greaterThan(12 * 1000 * 1000));
    expect(capture.isUsable, isTrue);

    final empty = CaptureInfo.fromMap({});
    expect(empty.width, 0);
    expect(empty.isUsable, isFalse);
  });
}
