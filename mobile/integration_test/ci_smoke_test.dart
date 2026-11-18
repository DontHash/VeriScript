import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/exports.dart';
import 'package:veriscript_mobile/processing.dart';

/// The emulator test CI runs on every pull request (docs/TECH_UPGRADE_PLAN.md
/// G). Self-contained: it draws its own page, so nothing is pushed first.
/// Reads it offline with ML Kit, exports a searchable and a protected PDF,
/// and prints CI_METRIC lines that scripts/perf_budget.py checks against
/// perf_budgets.json.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('read a page and export it, offline', (tester) async {
    final base = await getApplicationSupportDirectory();
    final root = Directory('${base.path}/ci-smoke');
    if (root.existsSync()) root.deleteSync(recursive: true);
    final store = DocumentStore(root..createSync(recursive: true));

    final page = img.Image(width: 1240, height: 1754);
    img.fill(page, color: img.ColorRgb8(250, 249, 245));
    for (var i = 0; i < 12; i++) {
      img.drawString(page, 'Ward 7 receipt total 12500 line $i',
          font: img.arial48, x: 80, y: 120 + i * 110, color: img.ColorRgb8(20, 20, 20));
    }
    final source = File('${root.path}/page.jpg')
      ..writeAsBytesSync(img.encodeJpg(page, quality: 90));

    final doc = await store.create('CI smoke');
    final scanned = await store.importImage(doc, source.path, align: false, enhance: false);
    final reader = OfflineProcessor('en');
    // Warm-up: the first read loads the model; page time is the second.
    await reader.recognize(scanned, autoRotate: false, checkDigits: false);
    final clock = Stopwatch()..start();
    await reader.recognize(scanned, autoRotate: false, checkDigits: false);
    final seconds = clock.elapsedMilliseconds / 1000;
    expect(scanned.text, contains('12500'));
    expect(scanned.lines.every((l) => (l['words'] as List?)?.isNotEmpty == true), isTrue);
    await store.save(doc);

    final pdf = await exportDocument(store, doc, ExportKind.searchablePdf);
    final locked = await exportDocument(store, doc, ExportKind.searchablePdf, password: 'ci-smoke-7');
    expect(await pdf.length(), greaterThan(10000));
    expect(String.fromCharCodes(await locked.readAsBytes()), contains('/Encrypt '));

    // ignore: avoid_print
    print('CI_METRIC emulator_page_read_seconds=$seconds');
    root.deleteSync(recursive: true);
  }, timeout: const Timeout(Duration(minutes: 10)));
}
