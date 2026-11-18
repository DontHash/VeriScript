import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:veriscript_mobile/pdf_stream.dart';

/// docs/TECH_UPGRADE_PLAN.md A4/E1: page-by-page PDF export.
void main() {
  late TrueTypeFont font;
  setUpAll(() {
    font = TrueTypeFont.parse(File('assets/Mukta-Regular.ttf').readAsBytesSync());
  });

  Uint8List jpeg(int w, int h) {
    final image = img.Image(width: w, height: h);
    img.fill(image, color: img.ColorRgb8(250, 248, 240));
    return img.encodeJpg(image, quality: 80);
  }

  /// SOI + a one-component SOF0 header: enough for pass-through embedding.
  Uint8List grayJpegHeader(int w, int h) => Uint8List.fromList([
    0xFF, 0xD8, 0xFF, 0xC0, 0x00, 0x0B, 0x08, h >> 8, h & 255, w >> 8, w & 255,
    0x01, 0x01, 0x11, 0x00, 0xFF, 0xD9,
  ]);

  Future<File> write(
    String name,
    Future<void> Function(StreamingPdfWriter w) pages, {
    TrueTypeFont? withFont,
  }) async {
    // Kept under build/ so the output can be inspected with other readers.
    final dir = Directory('build/test-output')..createSync(recursive: true);
    final file = File('${dir.path}/$name');
    final writer = await StreamingPdfWriter.open(
      file.path,
      title: 'नेपाल receipts',
      font: withFont,
    );
    await pages(writer);
    await writer.close();
    return file;
  }

  test('font maps Latin and Devanagari to real glyphs', () {
    expect(font.unitsPerEm, greaterThan(0));
    for (final ch in 'Total १२३ नेपाल'.runes.where((r) => r != 0x20)) {
      expect(font.glyph(ch), isNot(0), reason: String.fromCharCode(ch));
    }
    expect(font.advances[font.glyph('W'.codeUnitAt(0))], greaterThan(0));
  });

  test('subset keeps used glyphs and is much smaller than the font', () {
    final used = 'Total १२३'.runes.map(font.glyph).toSet();
    final subset = font.subset(used);
    expect(subset.length, lessThan(File('assets/Mukta-Regular.ttf').lengthSync() ~/ 4));
    final view = ByteData.sublistView(subset);
    expect(view.getUint32(0), 0x00010000);
    final tags = [
      for (var i = 0; i < view.getUint16(4); i++)
        String.fromCharCodes(subset.sublist(12 + i * 16, 16 + i * 16)),
    ];
    // Glyph ids are unchanged (Identity-H), so no cmap is needed.
    expect(tags, containsAll(['glyf', 'head', 'hhea', 'hmtx', 'loca', 'maxp']));
    expect(tags, isNot(contains('cmap')));
    File('build/test-output/subset.ttf')
      ..createSync(recursive: true)
      ..writeAsBytesSync(subset);
  });

  test('JPEG header is read without decoding', () {
    final info = JpegInfo.read(jpeg(40, 30))!;
    expect((info.width, info.height, info.components), (40, 30, 3));
    expect(JpegInfo.read(grayJpegHeader(8, 6))!.components, 1);
    expect(JpegInfo.read(Uint8List.fromList(utf8.encode('not a jpeg'))), isNull);
  });

  test('searchable PDF has one image per page and a hidden text layer', () async {
    final page = jpeg(900, 1200);
    final file = await write('searchable.pdf', (w) async {
      await w.addPage(page, lines: const [
        PdfTextLine('Invoice 12345', 100, 100, 400, 40),
        PdfTextLine('नेपाल सुन्दर देश हो', 100, 200, 500, 50),
      ]);
      await w.addPage(page, lines: const [PdfTextLine('पृष्ठ नम्बर १२३', 80, 900, 300, 40)]);
      await w.addPage(page); // a page with no text
    }, withFont: font);
    final bytes = file.readAsBytesSync();
    final text = latin1.decode(bytes);
    expect(text, startsWith('%PDF-1.7'));
    expect(text.trimRight(), endsWith('%%EOF'));
    expect(RegExp(r'/Type /Page\b').allMatches(text).length, 3);
    expect(RegExp(r'/Count 3').hasMatch(text), isTrue);
    expect(RegExp('/Filter /DCTDecode').allMatches(text).length, 3);
    expect(text, contains('3 Tr'));
    expect(text, contains('/ToUnicode'));
    // Images are passed through: three copies of the JPEG, nothing bigger.
    expect(bytes.length, lessThan(page.length * 3 + 60000));
    // Every xref offset points at its object.
    final xref = int.parse(RegExp(r'startxref\n(\d+)').firstMatch(text)!.group(1)!);
    final rows = text.substring(xref).split('\n');
    final count = int.parse(rows[1].split(' ')[1]);
    for (var id = 1; id < count; id++) {
      final row = rows[2 + id];
      if (row.endsWith('f ')) continue;
      final offset = int.parse(row.substring(0, 10));
      expect(text.substring(offset, offset + '$id 0 obj'.length), '$id 0 obj');
    }
  });

  test('image-only PDF embeds no font', () async {
    final file = await write('images.pdf', (w) => w.addPage(grayJpegHeader(300, 400)));
    final text = latin1.decode(file.readAsBytesSync());
    expect(text, isNot(contains('/FontFile2')));
    expect(text, contains('/DeviceGray'));
  });

  test('non-JPEG page images are refused, closing needs a page', () async {
    final dir = Directory.systemTemp.createTempSync('vs-pdf-');
    addTearDown(() => dir.deleteSync(recursive: true));
    final w = await StreamingPdfWriter.open('${dir.path}/x.pdf', title: 't');
    await expectLater(
      w.addPage(Uint8List.fromList([1, 2, 3])),
      throwsA(isA<FormatException>()),
    );
    await expectLater(w.close(), throwsStateError);
    await w.abandon();
  });
}
