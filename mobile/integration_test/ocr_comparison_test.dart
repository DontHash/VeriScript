import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/processing.dart';

/// Host-driven paired OCR comparison (mobile/tool/compare_ocr.py).
///
/// --dart-define options:
///   PACK     folder under app support with manifest/pages/gt (default ocr-comparison)
///   TAG      suffix for output folders, e.g. "_base" (default none)
///   ENGINES  comma list (default mlkit,rapidocr)
///   IMPORT   "1" = import each image with the default alignment and
///            enhancement first, the way a captured photo is processed.
///            A manifest row with "import": true is always imported.
const packName = String.fromEnvironment('PACK', defaultValue: 'ocr-comparison');
const tag = String.fromEnvironment('TAG');
const engines = String.fromEnvironment('ENGINES', defaultValue: 'mlkit,rapidocr');
const importFirst = String.fromEnvironment('IMPORT') == '1';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Paired OCR comparison', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Text('OCR comparison')));
    final base = await getApplicationSupportDirectory();
    final pack = Directory('${base.path}/$packName');
    final manifest = File('${pack.path}/manifest.json');
    // The host runner injects exact image bytes after this isolated app installs.
    for (var i = 0; i < 180 && !await manifest.exists(); i++) {
      await Future<void>.delayed(const Duration(seconds: 1));
    }
    expect(await manifest.exists(), true, reason: 'Host must inject the pack');
    final data =
        jsonDecode(await manifest.readAsString()) as Map<String, dynamic>;
    final store = DocumentStore(Directory('${base.path}/comparison-docs'));
    await store.root.create(recursive: true);
    for (final engine in engines.split(',')) {
      final output = Directory('${pack.path}/outputs/mobile_$engine$tag');
      await output.create(recursive: true);
      for (final row in data['entries'] as List) {
        final image = '${pack.path}/${row['image']}';
        var importSeconds = 0.0;
        late ScanPage page;
        if (importFirst || row['import'] == true) {
          final clock = Stopwatch()..start();
          final doc = await store.create(row['id']);
          page = await store.importImage(doc, image);
          clock.stop();
          importSeconds = clock.elapsedMilliseconds / 1000;
        } else {
          page = ScanPage(
            id: row['id'],
            source: image,
            path: image,
            width: row['width'],
            height: row['height'],
          );
        }
        final processor = OfflineProcessor(row['lang'], engine: engine);
        final clock = Stopwatch()..start();
        await processor.recognize(page);
        clock.stop();
        await File('${output.path}/${row['id']}.txt').writeAsString(page.text);
        await File('${output.path}/${row['id']}.json').writeAsString(
          jsonEncode({
            'seconds': clock.elapsedMilliseconds / 1000,
            'import_seconds': importSeconds,
            'rotation': processor.lastRotation,
            'reads': processor.lastReads,
            'tried': processor.lastTried,
            'ocr_width': page.width,
            'ocr_height': page.height,
            'image_sha256': row['sha256'],
            'page': page.toJson(),
          }),
        );
        // Empty OCR is a valid measured failure, not a reason to hide a page.
        // ignore: avoid_print
        print(
          'OCR_COMPARISON_DONE $engine ${row['id']} ${clock.elapsedMilliseconds}ms '
          'import ${(importSeconds * 1000).round()}ms rot ${processor.lastRotation} '
          '${page.width}x${page.height}',
        );
      }
    }
  }, timeout: const Timeout(Duration(minutes: 90)));
}
