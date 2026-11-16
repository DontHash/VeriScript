import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/processing.dart';

/// docs/TECH_UPGRADE_PLAN.md D5: both engines return word boxes. Reads
/// files/quality/*.png (pushed by hand, as for the C3 parity test) and
/// prints every line's words; mobile/tool/draw_words.py draws them on the
/// page for a visual check.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('word boxes from both engines', (tester) async {
    final dir = Directory('${(await getApplicationSupportDirectory()).path}/quality');
    final files = dir.listSync().whereType<File>().where((f) => f.path.endsWith('copy.png')).toList()
      ..sort((a, b) => a.path.compareTo(b.path));
    final out = <String, Object>{};
    for (final f in files.take(2)) {
      final size = await native.invokeMapMethod<String, dynamic>('dimensions', {'path': f.path});
      for (final engine in ['mlkit', 'rapidocr']) {
        final page = ScanPage(id: engine, source: f.path, path: f.path,
            width: size!['width'], height: size['height']);
        await (OfflineProcessor('en', engine: engine)).recognize(page, autoRotate: false, checkDigits: false);
        var lines = 0, withWords = 0, spelled = 0;
        for (final line in page.lines) {
          lines++;
          final words = line['words'] as List? ?? const [];
          if (words.isEmpty) continue;
          withWords++;
          if (words.map((w) => w['text']).join(' ') ==
              (line['text'] as String).trim().split(RegExp(r'\s+')).join(' ')) {
            spelled++;
          }
        }
        out['${f.uri.pathSegments.last}|$engine'] = {
          'lines': lines, 'withWords': withWords, 'spelled': spelled,
          'page': page.lines.map((l) => {'text': l['text'], 'bbox': l['bbox'], 'words': l['words']}).toList(),
        };
        expect(withWords, greaterThan(lines * .8), reason: '$engine on ${f.path}');
      }
    }
    final file = File('${dir.path}/../words.json');
    await file.writeAsString(jsonEncode(out));
    // ignore: avoid_print
    print('WORDS ${jsonEncode({for (final e in out.entries) e.key: {for (final k in ['lines', 'withWords', 'spelled']) k: (e.value as Map)[k]}})}');
  }, timeout: const Timeout(Duration(minutes: 15)));
}
