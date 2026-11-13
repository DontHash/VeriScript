import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/processing.dart';

Map<String, dynamic> reading() => {
  'text': 'Total 128',
  'blocks': [
    {
      'text': 'Total 128',
      'rect': {},
      'recognizedLanguages': [],
      'points': [],
      'lines': [
        {
          'text': 'Total 128',
          'rect': {'left': 10, 'top': 20, 'right': 300, 'bottom': 50},
          'recognizedLanguages': [],
          'points': [],
          'elements': [],
          'confidence': .95,
          'angle': 0.0,
        },
      ],
    },
  ],
};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('google_mlkit_text_recognizer');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(() {
    messenger.setMockMethodCallHandler(channel, null);
    messenger.setMockMethodCallHandler(native, null);
  });
  test('Native OCR failure preserves reviewed text and image', () async {
    final page = ScanPage(
      id: 'a',
      source: 'source',
      path: 'image.jpg',
      recognized: true,
      lines: [
        {'text': 'Total 123', 'original': 'Total 128', 'reviewed': true},
      ],
    );
    final before = page.toJson();
    messenger.setMockMethodCallHandler(native, (call) async {
      throw PlatformException(code: 'ocr', message: 'Invalid model');
    });
    await expectLater(
      OfflineProcessor(
        'ne',
        engine: 'rapidocr',
      ).recognize(page, autoRotate: false, checkDigits: false),
      throwsA(isA<PlatformException>()),
    );
    expect(page.toJson(), before);
  });
  test(
    'Cancellation during digit processing leaves reviewed image and text intact',
    () async {
      final root = await Directory.systemTemp.createTemp('veriscript-cancel-');
      addTearDown(() => root.delete(recursive: true));
      final page = ScanPage(
        id: 'a',
        source: 'source',
        path: '${root.path}/image.jpg',
        width: 900,
        height: 1200,
        recognized: true,
        lines: [
          {'text': 'Total 123', 'original': 'Total 128', 'reviewed': true},
        ],
      );
      final before = page.toJson();
      final worker = OfflineProcessor('en');
      var closed = false;
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'vision#closeTextRecognizer') {
          closed = true;
          return null;
        }
        return reading();
      });
      messenger.setMockMethodCallHandler(native, (call) async {
        if (call.method == 'digitCrop') {
          await File(call.arguments['out']).writeAsString('temporary crop');
          worker.cancelled = true;
        }
        return null;
      });
      await expectLater(
        worker.recognize(page, autoRotate: false),
        throwsStateError,
      );
      expect(page.toJson(), before);
      expect(root.listSync(), isEmpty);
      expect(closed, isTrue);
    },
  );
  test(
    'Successful re-recognition keeps corrections in the recoverable version',
    () async {
      messenger.setMockMethodCallHandler(
        channel,
        (call) async =>
            call.method == 'vision#closeTextRecognizer' ? null : reading(),
      );
      final page = ScanPage(
        id: 'a',
        source: 'source',
        path: 'image.jpg',
        recognized: true,
        lines: [
          {'text': 'Total 123', 'original': 'Total 128', 'reviewed': true},
        ],
      );
      final stages = <String>[];
      await OfflineProcessor('en').recognize(
        page,
        autoRotate: false,
        checkDigits: false,
        onProgress: stages.add,
      );
      expect(page.text, 'Total 128');
      expect(page.lines.single['reviewed'], false);
      expect(stages, contains('Reading text'));
      page.restorePreviousVersion();
      expect(page.text, 'Total 123');
      expect(page.lines.single['reviewed'], true);
    },
  );
}
