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
  group('orientation (docs/TECH_UPGRADE_PLAN.md D1)', () {
    late List<String> nativeCalls;
    late int reads;

    /// ML Kit reports [angles] on successive reads (the last one repeats).
    Future<OfflineProcessor> run(List<double> angles) async {
      final dir = await Directory.systemTemp.createTemp('veriscript-orient-');
      addTearDown(() => dir.delete(recursive: true));
      final image = File('${dir.path}/page.jpg')..writeAsStringSync('img');
      nativeCalls = [];
      reads = 0;
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'vision#closeTextRecognizer') return null;
        final value = reading();
        value['blocks'][0]['lines'][0]['angle'] =
            angles[reads < angles.length ? reads : angles.length - 1];
        reads++;
        return value;
      });
      messenger.setMockMethodCallHandler(native, (call) async {
        nativeCalls.add(call.method);
        switch (call.method) {
          case 'rotate':
            await File(call.arguments['out']).writeAsString('rotated');
            return {'path': call.arguments['out'], 'width': 1200, 'height': 900};
          case 'dimensions':
            return {'path': call.arguments['path'], 'width': 1200, 'height': 900};
        }
        return null;
      });
      final worker = OfflineProcessor('en');
      final page = ScanPage(
        id: 'a',
        source: image.path,
        path: image.path,
        width: 900,
        height: 1200,
      );
      await worker.recognize(page, checkDigits: false);
      expect(page.text, 'Total 128');
      return worker;
    }

    test('an upright page is read once', () async {
      final worker = await run([0]);
      expect(reads, 1);
      expect(worker.lastTried, [0]);
      expect(worker.lastRotation, 0);
      expect(nativeCalls, isNot(contains('rotate')));
    });

    test('an upside-down read goes straight to 180', () async {
      final worker = await run([180, 0]);
      expect(worker.lastTried, [0, 180]);
      expect(worker.lastRotation, 180);
      expect(nativeCalls.where((m) => m == 'rotate').length, 1);
    });

    test('a sideways read tries the matching quarter turn first', () async {
      // A line at 270 degrees (-90) is undone by turning 90 clockwise.
      expect((await run([-90, 0])).lastTried, [0, 90]);
      expect((await run([90, 0])).lastTried, [0, 270]);
      // A wrong first quarter turn falls to the opposite one next.
      expect((await run([-90, 180, 0])).lastTried, [0, 90, 270]);
    });

    test('nothing upright reads all four and keeps the best', () async {
      final worker = await run([180]);
      expect(worker.lastTried.toSet(), {0, 90, 180, 270});
      expect(reads, 4);
    });

    test('RapidOCR on Devanagari compares all four rotations', () async {
      final dir = await Directory.systemTemp.createTemp('veriscript-orient-');
      addTearDown(() => dir.delete(recursive: true));
      final image = File('${dir.path}/page.jpg')..writeAsStringSync('img');
      var reads = 0;
      messenger.setMockMethodCallHandler(native, (call) async {
        switch (call.method) {
          case 'rapidOcr':
            reads++;
            return [
              {
                'text': 'नेपाल सुन्दर देश हो',
                'confidence': .9,
                'angle': 0.0,
                'bbox': [10, 20, 300, 30],
              },
            ];
          case 'rotate':
            await File(call.arguments['out']).writeAsString('rotated');
            return {'path': call.arguments['out'], 'width': 1200, 'height': 900};
        }
        return null;
      });
      final worker = OfflineProcessor('ne', engine: 'rapidocr');
      await worker.recognize(
        ScanPage(id: 'a', source: image.path, path: image.path),
        checkDigits: false,
      );
      expect(reads, 4);
      expect(worker.lastTried, [0, 90, 180, 270]);
    });

    test('with no clues, quarter turns come before upside down', () {
      expect(rotationOrder([]), [90, 270, 180]);
    });
  });

  test('look-alike digits are flagged, never changed', () {
    // Seen in the 2026-11-15 measurement: Bengali zero in a Nepali account
    // number, and a Latin o inside a Devanagari date.
    expect(digitScriptIssue('बैंक खाता: ০१२३४५६७८९०१'), 'bengaliDigit');
    expect(digitScriptIssue('आजको मिति: २०८३/०७/o१'), 'letterInNumber');
    expect(digitScriptIssue('मिति २०८३/07/01'), 'mixedDigits');
    expect(digitScriptIssue('Invoice I2345'), 'letterInNumber');
    // Ordinary text and numbers stay quiet.
    expect(digitScriptIssue('कुल रकम: रु. १२,५००.७५'), isNull);
    expect(digitScriptIssue('Total: Rs. 3,000.00 for 10lbs'), isNull);
    expect(digitScriptIssue('Hello world, look'), isNull);
    expect(digitScriptIssue('Date: 2026/10/17'), isNull);
    // Values still compare across scripts; the script is reported apart.
    expect(digitGroups('০१२'), ['012']);
    expect(compareDigitReadings('खाता ০१२', 'खाता ०१२'), 'matched');
    final line = {
      'text': 'खाता ০१२',
      'confidence': .99,
      'digitScript': 'bengaliDigit',
      'digitCheck': 'matched',
    };
    expect(needsReview(line), isTrue);
    expect(reviewLabel(line), contains('Look-alike digit'));
    expect(reviewLabel({...line, 'reviewed': true}), 'Confirmed by you');
  });

  test('ML Kit number lines are re-read by the other engine by default', () async {
    final dir = await Directory.systemTemp.createTemp('veriscript-cross-');
    addTearDown(() => dir.delete(recursive: true));
    final image = File('${dir.path}/page.jpg')..writeAsStringSync('img');
    messenger.setMockMethodCallHandler(
      channel,
      (call) async => call.method == 'vision#closeTextRecognizer' ? null : reading(),
    );
    final calls = <String>[];
    messenger.setMockMethodCallHandler(native, (call) async {
      calls.add(call.method);
      if (call.method == 'digitCrop') {
        await File(call.arguments['out']).writeAsString('crop');
      }
      if (call.method == 'rapidOcrLine') {
        expect(call.arguments['language'], 'en');
        return {'text': 'Total 129', 'confidence': .9};
      }
      return null;
    });
    final worker = OfflineProcessor('en');
    expect(worker.digitMode, 'cross');
    expect(OfflineProcessor('en', engine: 'rapidocr').digitMode, 'same');
    final page = ScanPage(id: 'a', source: image.path, path: image.path);
    await worker.recognize(page, autoRotate: false);
    final line = page.lines.single;
    expect(calls, containsAllInOrder(['digitCrop', 'rapidOcrLine']));
    expect(line['digitMethod'], 'other-engine-enlarged-contrast-crop');
    expect(line['digitAlternative'], 'Total 129');
    expect(line['digitCheck'], 'conflict');
    expect(line['text'], 'Total 128', reason: 'the first reading is never replaced');
    expect(reviewLabel(line), 'Second reader disagrees on digits · tap to compare');
  });

  test('looksUpright needs enough text, mostly on upright lines', () {
    Map<String, dynamic> line(String text, double angle) => {
      'text': text,
      'angle': angle,
      'bbox': [0, 0, 300, 30],
    };
    expect(looksUpright([line('Invoice 12345', 2)]), isTrue);
    expect(looksUpright([line('Invoice 12345', 178)]), isFalse);
    expect(looksUpright([line('ok', 0)]), isFalse); // too little text
    expect(
      looksUpright([line('Invoice 12345 total', 0), line('Total', 180)]),
      isTrue,
    );
  });

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
