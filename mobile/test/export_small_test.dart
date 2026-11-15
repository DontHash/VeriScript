import 'dart:convert';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/exports.dart';

/// docs/TECH_UPGRADE_PLAN.md E3 (phone): "Smaller PDF for sharing" shrinks
/// each page picture natively and keeps the same text layer.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  test('small PDFs shrink every page and keep the text', () async {
    final root = await Directory.systemTemp.createTemp('vs-small-');
    addTearDown(() => root.delete(recursive: true));
    final store = DocumentStore(root);
    final doc = await store.create('Receipts');
    final big = img.encodeJpg(img.Image(width: 2480, height: 3508), quality: 95);
    for (var i = 0; i < 2; i++) {
      final path = '${store.directory(doc)}/page_$i.jpg';
      await File(path).writeAsBytes(big);
      doc.pages.add(ScanPage(
        id: '$i', source: path, path: path, width: 2480, height: 3508, recognized: true,
        lines: [
          {'text': 'Total १२,५००.७५', 'bbox': [200, 300, 1200, 60]},
        ],
      ));
    }
    final shrinks = <Map>[];
    messenger.setMockMethodCallHandler(native, (call) async {
      if (call.method != 'shrink') return null;
      shrinks.add(call.arguments as Map);
      final side = call.arguments['maxSide'] as int;
      final small = img.encodeJpg(
        img.Image(width: (side * 2480 / 3508).round(), height: side),
        quality: call.arguments['quality'] as int,
      );
      await File(call.arguments['out'] as String).writeAsBytes(small);
      return {'path': call.arguments['out'], 'width': 1240, 'height': side};
    });
    addTearDown(() => messenger.setMockMethodCallHandler(native, null));

    final full = await exportDocument(store, doc, ExportKind.searchablePdf);
    expect(shrinks, isEmpty);
    final small = await exportDocument(store, doc, ExportKind.searchablePdf, smallPdf: true);
    expect(shrinks.length, 2);
    expect(shrinks.first['maxSide'], smallPdfMaxSide);
    expect(shrinks.first['quality'], smallPdfQuality);
    expect(await small.length(), lessThan(await full.length()));
    final text = latin1.decode(await small.readAsBytes());
    expect(text, contains('/Width 1240'));
    expect(text, contains('3 Tr')); // the invisible text layer is still there
    // No scratch files are left in the document folder.
    expect(Directory(store.directory(doc)).listSync().where((f) => f.path.endsWith('.page.jpg')), isEmpty);
  });
}
