import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/processing.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Paired OCR comparison', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Text('OCR comparison')));
    final base = await getApplicationSupportDirectory();
    final pack = Directory('${base.path}/ocr-comparison');
    final manifest = File('${pack.path}/manifest.json');
    // The host runner injects exact image bytes after this isolated app installs.
    for (var i = 0; i < 180 && !await manifest.exists(); i++) {
      await Future<void>.delayed(const Duration(seconds: 1));
    }
    expect(await manifest.exists(), true, reason: 'Host must inject the pack');
    final data =
        jsonDecode(await manifest.readAsString()) as Map<String, dynamic>;
    for (final engine in ['mlkit', 'rapidocr']) {
      final output = Directory('${pack.path}/outputs/mobile_$engine');
      await output.create(recursive: true);
      for (final row in data['entries'] as List) {
        final page = ScanPage(
          id: row['id'],
          source: '${pack.path}/${row['image']}',
          path: '${pack.path}/${row['image']}',
          width: row['width'],
          height: row['height'],
        );
        final clock = Stopwatch()..start();
        await OfflineProcessor(row['lang'], engine: engine).recognize(page);
        clock.stop();
        await File('${output.path}/${page.id}.txt').writeAsString(page.text);
        await File('${output.path}/${page.id}.json').writeAsString(
          jsonEncode({
            'seconds': clock.elapsedMilliseconds / 1000,
            'image_sha256': row['sha256'],
            'page': page.toJson(),
          }),
        );
        // Empty OCR is a valid measured failure, not a reason to hide a page.
        // ignore: avoid_print
        print(
          'OCR_COMPARISON_DONE $engine ${page.id} ${clock.elapsedMilliseconds}ms',
        );
      }
    }
  }, timeout: const Timeout(Duration(minutes: 45)));
}
