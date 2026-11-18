import 'dart:convert';
import 'dart:io';
import 'package:archive/archive_io.dart';
import 'package:flutter/services.dart';
import 'package:image/image.dart' as img;
import 'documents.dart';
import 'pdf_stream.dart';

TrueTypeFont? _font;

/// The bundled Unicode font, parsed once per app run.
Future<TrueTypeFont> _exportFont() async {
  return _font ??= TrueTypeFont.parse(
    (await rootBundle.load('assets/Mukta-Regular.ttf')).buffer.asUint8List(),
  );
}

/// Page image bytes as JPEG. Pages are stored as JPEG; anything else is
/// re-encoded once so the PDF can embed it without decoding later.
Future<Uint8List> _jpegOf(String path) async {
  final bytes = await File(path).readAsBytes();
  if (JpegInfo.read(bytes) != null) return bytes;
  final decoded = img.decodeImage(bytes);
  if (decoded == null) throw StateError('A page image could not be read.');
  return img.encodeJpg(decoded, quality: 92);
}

/// Long side of a "small" PDF page: A4 at 150 DPI.
const smallPdfMaxSide = 1754;
const smallPdfQuality = 60;

/// A page re-encoded for a smaller PDF (shared by messaging and email). The
/// page keeps its proportions, so the text layer (in page-image pixels)
/// still lines up: the writer scales boxes by the original width.
Future<Uint8List> _smallJpegOf(String path, String scratch) async {
  final out = '$scratch.page.jpg';
  try {
    await native.invokeMethod('shrink', {
      'path': path,
      'out': out,
      'maxSide': smallPdfMaxSide,
      'quality': smallPdfQuality,
    });
    return await File(out).readAsBytes();
  } finally {
    final file = File(out);
    if (await file.exists()) await file.delete();
  }
}

PdfTextLine? _box(String text, Object? bbox) {
  if (bbox is! List || bbox.length != 4) return null;
  return PdfTextLine(
    text,
    (bbox[0] as num).toDouble(),
    (bbox[1] as num).toDouble(),
    (bbox[2] as num).toDouble(),
    (bbox[3] as num).toDouble(),
  );
}

/// The words of [line] with usable boxes, or null when the line should be
/// placed as one run: no words, or the text was corrected so the words no
/// longer spell it (docs/TECH_UPGRADE_PLAN.md D5).
List<PdfTextLine>? lineWords(Map<String, dynamic> line) {
  final words = line['words'];
  if (words is! List || words.isEmpty) return null;
  final texts = [for (final w in words) (w as Map)['text'] as String? ?? ''];
  final text = (line['text'] as String? ?? '')
      .trim()
      .split(RegExp(r'\s+'))
      .join(' ');
  if (texts.join(' ') != text) return null;
  final out = <PdfTextLine>[];
  for (final w in words) {
    final box = _box((w as Map)['text'] as String? ?? '', w['bbox']);
    if (box == null || box.width <= 0 || box.height <= 0) return null;
    out.add(box);
  }
  return out;
}

/// Recognised text with usable boxes, in page-image pixels: word by word
/// when the words still spell the line, else the whole line (E1, D5).
List<PdfTextLine> textRuns(ScanPage page) => [
  for (final line in page.lines)
    ...(lineWords(line) ??
        [?_box(line['text'] as String? ?? '', line['bbox'])]),
];

String xmlEscape(String value) => value
    .replaceAll(RegExp(r'[\x00-\x08\x0B\x0C\x0E-\x1F]'), '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');

Uint8List wordDocument(String title, Iterable<String> pages) {
  final archive = Archive();
  void add(String name, String text) {
    final bytes = utf8.encode(text);
    archive.addFile(ArchiveFile(name, bytes.length, bytes));
  }

  add(
    '[Content_Types].xml',
    '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
  );
  add(
    '_rels/.rels',
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
  );
  final body = StringBuffer();
  body.write(
    '<w:p><w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:t>${xmlEscape(title)}</w:t></w:r></w:p>',
  );
  var index = 0;
  for (final text in pages) {
    if (index++ > 0) body.write('<w:p><w:r><w:br w:type="page"/></w:r></w:p>');
    for (final line in text.split('\n')) {
      body.write(
        '<w:p><w:r><w:rPr><w:rFonts w:ascii="Mukta" w:hAnsi="Mukta" w:cs="Mukta"/>'
        '<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr><w:t xml:space="preserve">${xmlEscape(line)}</w:t></w:r></w:p>',
      );
    }
  }
  add(
    'word/document.xml',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>$body'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        '</w:body></w:document>',
  );
  return Uint8List.fromList(ZipEncoder().encode(archive));
}

enum ExportKind {
  imagePdf,
  searchablePdf,
  digitalPdf,
  docx,
  txt,
  markdown,
  corrections,
  bundle,
}

const _save = MethodChannel('veriscript/save');

/// The media type a "Save to…" picker should be told for an export.
String exportMime(String path) {
  final ext = path.split('.').last.toLowerCase();
  return switch (ext) {
    'pdf' => 'application/pdf',
    'docx' =>
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'txt' => 'text/plain',
    'md' => 'text/markdown',
    'json' => 'application/json',
    _ => 'application/octet-stream', // .veriscript bundles and anything else
  };
}

/// "Save to…" through Android's own picker (docs/TECH_UPGRADE_PLAN.md E5).
/// True when saved, false when the user closed the picker.
Future<bool> saveExportAs(String path) async {
  final name = path.split(RegExp(r'[\\/]')).last;
  final saved = await _save.invokeMethod<bool>('saveAs', {
    'path': path,
    'name': name,
    'mime': exportMime(path),
  });
  return saved ?? false;
}

/// Phone -> desktop bundle (docs/TECH_UPGRADE_PLAN.md B4): the original page
/// pictures plus this phone's readings and corrections, for the full check in
/// VeriScript Desktop (`veriscript/document/bundle.py` reads it). Written
/// straight to disk one page at a time: a long document never sits in memory.
const bundleFormat = 'veriscript-bundle';
const bundleVersion = 1;

Future<void> writeBundle(
  String out,
  ScanDocument doc,
  List<ScanPage> pages, {
  void Function(int, int)? progress,
  bool Function()? cancelled,
  DateTime? now,
}) async {
  final zip = ZipFileEncoder()..create(out, level: 0);
  final scratch = <File>[];
  try {
    final manifestPages = <Map<String, dynamic>>[];
    for (var i = 0; i < pages.length; i++) {
      if (cancelled?.call() == true) throw StateError('Export cancelled');
      final page = pages[i];
      final source = File(page.path);
      final head = await source
          .openRead(0, 8)
          .fold<List<int>>([], (a, b) => a..addAll(b));
      final isJpeg = head.length > 2 && head[0] == 0xFF && head[1] == 0xD8;
      const pngMagic = [0x89, 0x50, 0x4E, 0x47];
      final isPng =
          head.length >= 4 &&
          List.generate(4, (k) => head[k] == pngMagic[k]).every((x) => x);
      var file = source;
      var ext = isPng ? 'png' : 'jpg';
      if (!isJpeg && !isPng) {
        // Rare: other formats become a JPEG so the desktop can read them.
        file = File('$out.page$i.jpg');
        await file.writeAsBytes(await _jpegOf(page.path), flush: true);
        scratch.add(file);
        ext = 'jpg';
      }
      final name = 'pages/${(i + 1).toString().padLeft(4, '0')}.$ext';
      // Page pictures are already compressed: store them as they are.
      final entry = ArchiveFile.stream(name, InputFileStream(file.path))
        ..compression = CompressionType.none;
      zip.addArchiveFile(entry);
      await entry.close();
      manifestPages.add({
        'image': name,
        'width': page.width,
        'height': page.height,
        'recognized': page.recognized,
        'note': page.note,
        'lines': page.lines,
      });
      progress?.call(i + 1, pages.length);
    }
    final manifest = const JsonEncoder.withIndent(' ').convert({
      'format': bundleFormat,
      'version': bundleVersion,
      'title': doc.title,
      'created': (now ?? DateTime.now()).toUtc().toIso8601String(),
      'source': 'VeriScript Android',
      'pages': manifestPages,
    });
    zip.addArchiveFile(ArchiveFile.string('manifest.json', manifest));
    await zip.close();
  } catch (_) {
    try {
      await zip.close();
    } catch (_) {}
    rethrow;
  } finally {
    for (final f in scratch) {
      if (await f.exists()) await f.delete();
    }
  }
}

extension ExportLabels on ExportKind {
  String get label => switch (this) {
    ExportKind.imagePdf => 'PDF · page images',
    ExportKind.searchablePdf => 'PDF · searchable scans',
    ExportKind.digitalPdf => 'PDF · digital text layout',
    ExportKind.docx => 'Word · editable DOCX',
    ExportKind.txt => 'Plain text · TXT',
    ExportKind.markdown => 'Markdown · MD',
    ExportKind.corrections => 'Review data · JSON',
    ExportKind.bundle => 'For VeriScript Desktop · bundle',
  };
  bool get needsText =>
      this != ExportKind.imagePdf && this != ExportKind.bundle;
  String get guidance => switch (this) {
    ExportKind.imagePdf =>
      'Keep the original page appearance for sharing or printing. No text recognition needed.',
    ExportKind.searchablePdf =>
      'Keep the page image and add recognized text for search and selection. A good choice for Nepali scans.',
    ExportKind.digitalPdf =>
      'Create new pages from recognized text. Spacing and Nepali text selection can differ; use searchable scans when the original layout matters.',
    ExportKind.docx =>
      'Edit the recognized text in Word or another document editor. Page formatting will differ from the scan.',
    ExportKind.txt =>
      'Copy or reuse just the recognized text, without page formatting.',
    ExportKind.markdown =>
      'Use recognized text with document and page headings in a notes app.',
    ExportKind.corrections =>
      'Save original readings, corrections and number-review evidence for checking later.',
    ExportKind.bundle =>
      'Open this document on a computer for the full check: columns, tables and number review. Holds the original pages and your corrections. Move it by cable, USB stick or any app; nothing is uploaded.',
  };
  String get extension => switch (this) {
    ExportKind.docx => 'docx',
    ExportKind.txt => 'txt',
    ExportKind.markdown => 'md',
    ExportKind.corrections => 'json',
    ExportKind.bundle => 'veriscript',
    _ => 'pdf',
  };
}

Future<File> exportDocument(
  DocumentStore store,
  ScanDocument doc,
  ExportKind kind, {
  void Function(int, int)? progress,
  bool Function()? cancelled,
  bool smallPdf = false,
  String? password,
}) async {
  final pages = doc.selected.toList();
  if (pages.isEmpty) throw StateError('Select at least one page.');
  if (kind.needsText && pages.any((p) => !p.recognized)) {
    throw StateError('Recognize every selected page before text export.');
  }
  final stem = doc.title
      .replaceAll(RegExp(r'[^\p{L}\p{N}_ -]', unicode: true), '')
      .trim();
  final file = File(
    '${store.directory(doc)}/${stem.isEmpty ? 'document' : stem}_${kind.name}_${DateTime.now().millisecondsSinceEpoch}.${kind.extension}',
  );
  final pending = File('${file.path}.pending');
  try {
    if (kind == ExportKind.imagePdf || kind == ExportKind.searchablePdf) {
      // Page by page: only one page image is in memory at a time.
      final font = kind == ExportKind.searchablePdf
          ? await _exportFont()
          : null;
      final pdf = await StreamingPdfWriter.open(
        pending.path,
        title: doc.title,
        font: font,
        // E5: AES-256 (revision 6); the password is not stored anywhere.
        password: password,
      );
      try {
        for (var index = 0; index < pages.length; index++) {
          if (cancelled?.call() == true) throw StateError('Export cancelled');
          final page = pages[index];
          await pdf.addPage(
            smallPdf
                ? await _smallJpegOf(page.path, pending.path)
                : await _jpegOf(page.path),
            pixelWidth: page.width,
            pixelHeight: page.height,
            // Hidden text does not alter the scan; it makes OCR and
            // corrections selectable and searchable.
            lines: kind == ExportKind.searchablePdf ? textRuns(page) : const [],
          );
          progress?.call(index + 1, pages.length);
        }
        await pdf.close();
      } catch (_) {
        await pdf.abandon();
        rethrow;
      }
    } else if (kind == ExportKind.bundle) {
      await writeBundle(
        pending.path,
        doc,
        pages,
        progress: progress,
        cancelled: cancelled,
      );
    } else if (kind == ExportKind.digitalPdf) {
      // Android's text layout handles Devanagari shaping and font fallback.
      await native.invokeMethod('textPdf', {
        'out': pending.path,
        'title': doc.title,
        'pages': pages.map((p) => p.text).toList(),
      });
    } else if (kind == ExportKind.docx) {
      await pending.writeAsBytes(
        wordDocument(doc.title, pages.map((p) => p.text)),
        flush: true,
      );
    } else if (kind == ExportKind.corrections) {
      await pending.writeAsString(
        const JsonEncoder.withIndent('  ').convert({
          'version': 1,
          'engine': 'bundled-mlkit',
          'title': doc.title,
          'pages': pages
              .map(
                (p) => {
                  'id': p.id,
                  'width': p.width,
                  'height': p.height,
                  'lines': p.lines,
                },
              )
              .toList(),
        }),
        flush: true,
      );
    } else {
      final text = kind == ExportKind.markdown
          ? '# ${doc.title}\n\n${pages.asMap().entries.map((e) => '## Page ${e.key + 1}\n\n${e.value.text}').join('\n\n')}'
          : pages.map((p) => p.text).join('\n\n\f\n\n');
      await pending.writeAsString(text, flush: true);
    }
    if (cancelled?.call() == true) throw StateError('Export cancelled');
    await pending.rename(file.path);
    doc.exports = [...doc.exports, file.path];
    await store.save(doc);
    return file;
  } finally {
    if (await pending.exists()) await pending.delete();
  }
}
