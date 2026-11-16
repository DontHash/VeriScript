import 'dart:convert';
import 'dart:io';
import 'package:archive/archive_io.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/exports.dart';

/// docs/TECH_UPGRADE_PLAN.md B4: the "For VeriScript Desktop" export holds
/// the original page pictures (byte for byte, not recompressed), only the
/// selected pages, and every line with its corrections, in the format
/// `veriscript/document/bundle.py` reads. Set VERISCRIPT_BUNDLE_OUT to keep
/// a copy for the desktop-side check.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('desktop bundle carries the original pages and the corrections', () async {
    final root = await Directory.systemTemp.createTemp('vs-bundle-');
    addTearDown(() => root.delete(recursive: true));
    final store = DocumentStore(root);
    final doc = await store.create('वडा ७ record');
    final pictures = {
      'page_0.jpg': img.encodeJpg(img.Image(width: 300, height: 420), quality: 90),
      'page_1.png': img.encodePng(img.Image(width: 420, height: 300)),
      'page_2.bmp': img.encodeBmp(img.Image(width: 200, height: 280)),
      'page_3.jpg': img.encodeJpg(img.Image(width: 10, height: 10)),
    };
    var i = 0;
    for (final entry in pictures.entries) {
      final path = '${store.directory(doc)}/${entry.key}';
      await File(path).writeAsBytes(entry.value);
      final image = img.decodeImage(entry.value)!;
      doc.pages.add(ScanPage(
        id: '$i', source: path, path: path, width: image.width, height: image.height,
        recognized: i == 0, included: i != 3, note: i == 1 ? 'torn corner' : '',
        lines: i == 0
            ? [
                {'text': 'कुल रकम १२,५००', 'original': 'कुल रकम १२,६००', 'reviewed': true,
                 'confidence': .91, 'bbox': [10, 20, 280, 40]},
              ]
            : [],
      ));
      i++;
    }
    final progress = <int>[];
    final file = await exportDocument(store, doc, ExportKind.bundle,
        progress: (done, _) => progress.add(done));
    expect(file.path, endsWith('.veriscript'));
    expect(progress, [1, 2, 3]); // the unselected page is left out

    final zip = ZipDecoder().decodeBytes(await file.readAsBytes());
    final manifest = jsonDecode(utf8.decode(zip.findFile('manifest.json')!.content))
        as Map<String, dynamic>;
    expect(manifest['format'], 'veriscript-bundle');
    expect(manifest['version'], 1);
    expect(manifest['title'], 'वडा ७ record');
    final pages = (manifest['pages'] as List).cast<Map<String, dynamic>>();
    expect(pages.map((p) => p['image']),
        ['pages/0001.jpg', 'pages/0002.png', 'pages/0003.jpg']);
    // JPEG and PNG pages are the original bytes, stored without recompression.
    expect(zip.findFile('pages/0001.jpg')!.content, pictures['page_0.jpg']);
    expect(zip.findFile('pages/0002.png')!.content, pictures['page_1.png']);
    expect(zip.findFile('pages/0001.jpg')!.compression, CompressionType.none);
    // A BMP becomes a JPEG the desktop can read.
    final bmp = zip.findFile('pages/0003.jpg')!.content;
    expect(bmp.take(2), [0xFF, 0xD8]);
    expect(pages[0]['lines'][0]['original'], 'कुल रकम १२,६००');
    expect(pages[0]['recognized'], true);
    expect(pages[1]['note'], 'torn corner');
    // No scratch files are left in the document folder.
    expect(Directory(store.directory(doc)).listSync().where((f) => f.path.contains('.page')),
        isEmpty);

    final keep = Platform.environment['VERISCRIPT_BUNDLE_OUT'];
    if (keep != null) await file.copy(keep);
  });
}
