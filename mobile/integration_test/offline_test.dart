import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/processing.dart';
import 'package:veriscript_mobile/exports.dart';

Future<File> fixture(String path, String text) async {
  final recorder = ui.PictureRecorder();
  final canvas = Canvas(recorder);
  canvas.drawRect(
    const Rect.fromLTWH(0, 0, 900, 1200),
    Paint()..color = Colors.white,
  );
  final painter = TextPainter(
    text: TextSpan(
      text: text,
      style: const TextStyle(
        fontFamily: 'Mukta',
        fontSize: 45,
        color: Colors.black,
      ),
    ),
    textDirection: TextDirection.ltr,
  )..layout(maxWidth: 780);
  painter.paint(canvas, const Offset(60, 120));
  final picture = recorder.endRecording();
  final image = await picture.toImage(900, 1200);
  final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
  final file = await File(path).writeAsBytes(bytes!.buffer.asUint8List());
  image.dispose();
  picture.dispose();
  return file;
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'Bundled first-launch OCR, geometry, draft and every export without connectivity',
    (tester) async {
      // Real Android plugins. Run on an emulator with Wi-Fi/data disabled.
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: Text('Offline verification'))),
      );
      final base = await getApplicationDocumentsDirectory();
      final root = Directory(
        '${base.path}/offline-verification/${DateTime.now().microsecondsSinceEpoch}',
      );
      await root.create(recursive: true);
      final store = DocumentStore(root);
      final doc = await store.create('Offline test किताब');
      final english = await fixture(
        '${root.path}/english.png',
        'VERISCRIPT OFFLINE\nInvoice 12345\nFirst page with readable text.\nSecond line for document testing.',
      );
      final nepali = await fixture(
        '${root.path}/nepali.png',
        'नेपाल सुन्दर देश हो\nयो एउटा किताब हो\nपृष्ठ नम्बर १२३',
      );
      final a = await store.importImage(doc, english.path, align: false);
      final b = await store.importImage(doc, nepali.path, align: false);
      final turn = await native.invokeMapMethod<String, dynamic>('rotate', {
        'path': a.path,
        'out': '${root.path}/sideways.jpg',
        'degrees': 90,
      });
      a.path = turn!['path'];
      a.width = turn['width'];
      a.height = turn['height'];
      await OfflineProcessor('en').recognize(a);
      expect(a.text, contains('12345'));
      final number = a.lines.firstWhere(
        (l) => (l['text'] as String).contains('12345'),
      );
      expect(number['digitAlternative'], contains('12345'));
      expect(number['digitCheck'], 'matched');
      expect(needsReview(number), true);
      expect(a.width, lessThan(a.height));
      expect(a.lines.first['text'], 'VERISCRIPT OFFLINE');
      expect(
        (a.lines.first['bbox'] as List)[1],
        lessThan(a.height * .25),
        reason: 'The heading must be physically upright near the page top',
      );
      await OfflineProcessor('ne').recognize(b, autoRotate: false);
      expect(b.text, contains('नेपाल'));
      expect(b.width, 1800, reason: 'Small document pages are enlarged 2×');
      expect(b.height, 2400);
      expect(b.lines.where((l) => l['digitCheck'] != null), isNotEmpty);
      final crop = await native.invokeMapMethod<String, dynamic>('crop', {
        'path': b.path,
        'out': '${root.path}/crop.jpg',
        'points': [
          [.05, .05],
          [.95, .05],
          [.95, .95],
          [.05, .95],
        ],
      });
      expect(crop!['width'], greaterThan(60));
      final restored = await native.invokeMapMethod<String, dynamic>(
        'restore',
        {'path': b.path, 'out': '${root.path}/aligned.jpg'},
      );
      expect(restored!['width'], greaterThan(60));
      await expectLater(
        native.invokeMethod('crop', {
          'path': b.path,
          'out': '${root.path}/bad.jpg',
          'points': [
            [0, 0],
            [1, 1],
            [1, 0],
            [0, 1],
          ],
        }),
        throwsA(isA<Exception>()),
      );
      for (final kind in ExportKind.values) {
        final file = await exportDocument(store, doc, kind);
        expect(await file.length(), greaterThan(20));
      }
      final pdf = doc.exports.firstWhere((p) => p.contains('imagePdf'));
      final info = await native.invokeMapMethod<String, dynamic>('pdfInfo', {
        'path': pdf,
      });
      expect(info!['pages'], 2);
      await native.invokeMethod('pdfPage', {
        'path': pdf,
        'out': '${root.path}/render.jpg',
        'index': 0,
      });
      await store.save(doc);
      expect((await store.list()).single.selected.length, 2);
      final support = await getApplicationSupportDirectory();
      final book = File('${support.path}/book-fixture.mp4');
      expect(
        await book.exists(),
        isTrue,
        reason:
            'Run through tool/verify_android.py to inject the fixture after installation',
      );
      if (await book.exists()) {
        final result = await native.invokeMapMethod<String, dynamic>('video', {
          'path': book.path,
          'out': '${root.path}/book-pages',
          'layout': 'spread',
        });
        final pages = result!['pages'] as List;
        expect(
          pages.length,
          4,
          reason:
              'Two distinct stable spreads; repeated holds must not duplicate pages',
        );
        expect(pages.map((p) => p['side']).toList(), [
          'left',
          'right',
          'left',
          'right',
        ]);
        final bookDoc = await store.create('Book capture');
        for (final p in pages) {
          await store.importImage(bookDoc, p['path'], align: false);
        }
        await OfflineProcessor(
          'en',
        ).recognize(bookDoc.pages[0], autoRotate: false);
        await OfflineProcessor(
          'en',
        ).recognize(bookDoc.pages[1], autoRotate: false);
        expect(bookDoc.pages[0].text, contains('LEFT'));
        expect(bookDoc.pages[1].text, contains('RIGHT'));
      }
      await File('${base.path}/offline-result.txt').writeAsString(
        'PASS\nEnglish: ${a.text}\nNepali: ${b.text}\nExports: ${doc.exports.join('\n')}',
      );
    },
  );
}
