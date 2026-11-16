import 'dart:io';
import 'dart:math';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/exports.dart';

/// docs/TECH_UPGRADE_PLAN.md A4: a 150-page searchable PDF export must not
/// hold the document in memory. Pages are A4 at 300 DPI (2480x3508 JPEG)
/// with 30 recognised lines each; the test records the process's peak
/// resident memory before and after each export (ProcessInfo.maxRss).
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('150-page export memory', (tester) async {
    final base = await getApplicationSupportDirectory();
    final root = Directory('${base.path}/export-memory');
    if (await root.exists()) await root.delete(recursive: true);
    final store = DocumentStore(root..createSync(recursive: true));
    final doc = await store.create('Export memory');
    final dir = store.directory(doc);

    // One realistic page: paper texture and dark text-like bars, so the JPEG
    // is a typical 1-2 MB camera-page size, not a tiny flat image.
    const w = 2480, h = 3508;
    final page = img.Image(width: w, height: h);
    final random = Random(7);
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        final v = 235 + random.nextInt(20);
        page.setPixelRgb(x, y, v, v, v - 6);
      }
    }
    final lines = <Map<String, dynamic>>[];
    for (var i = 0; i < 30; i++) {
      final top = 200 + i * 105;
      for (var x = 200; x < 2200; x += 34) {
        if (random.nextInt(6) == 0) continue;
        img.fillRect(page, x1: x, y1: top, x2: x + 26, y2: top + 46,
            color: img.ColorRgb8(30, 30, 30));
      }
      lines.add({
        'text': 'पृष्ठ ${i + 1}: नेपाल सरकार शिक्षा मन्त्रालय रकम रु. १२,५००.७५',
        'bbox': [200, top, 2000, 46],
        'confidence': .95,
        'reviewed': false,
      });
    }
    final jpeg = img.encodeJpg(page, quality: 85);
    for (var i = 0; i < 150; i++) {
      final path = '$dir/page_$i.jpg';
      await File(path).writeAsBytes(jpeg);
      doc.pages.add(ScanPage(
        id: '$i',
        source: path,
        path: path,
        width: w,
        height: h,
        recognized: true,
        lines: [for (final line in lines) Map<String, dynamic>.from(line)],
      ));
    }
    await store.save(doc);

    // The bundle (B4) goes first: maxRss is a high-water mark.
    for (final (kind, small) in [
      (ExportKind.bundle, false),
      (ExportKind.searchablePdf, false),
      (ExportKind.imagePdf, false),
      (ExportKind.searchablePdf, true),
    ]) {
      final before = ProcessInfo.maxRss;
      final current = ProcessInfo.currentRss;
      final clock = Stopwatch()..start();
      final file = await exportDocument(store, doc, kind, smallPdf: small);
      clock.stop();
      final after = ProcessInfo.maxRss;
      // ignore: avoid_print
      print('EXPORT_MEMORY ${kind.name}${small ? '_small' : ''} pages=150 page_jpeg=${jpeg.length} '
          'pdf_bytes=${await file.length()} seconds=${clock.elapsedMilliseconds / 1000} '
          'rss_before=${current ~/ 1048576}MB peak_before=${before ~/ 1048576}MB '
          'peak_after=${after ~/ 1048576}MB');
      if (!small) expect(await file.length(), greaterThan(jpeg.length * 150));
      await file.delete(); // keep the emulator's storage free for the next export
    }
    await root.delete(recursive: true);
  }, timeout: const Timeout(Duration(minutes: 30)));
}
