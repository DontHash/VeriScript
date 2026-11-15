import 'dart:convert';
import 'dart:io';
import 'package:archive/archive.dart';
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

/// Recognised lines with usable boxes, in page-image pixels.
List<PdfTextLine> _textLines(ScanPage page) => [
  for (final line in page.lines)
    if (line['bbox'] is List && (line['bbox'] as List).length == 4)
      PdfTextLine(
        line['text'] as String? ?? '',
        (line['bbox'][0] as num).toDouble(),
        (line['bbox'][1] as num).toDouble(),
        (line['bbox'][2] as num).toDouble(),
        (line['bbox'][3] as num).toDouble(),
      ),
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
  };
  bool get needsText => this != ExportKind.imagePdf;
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
  };
  String get extension => switch (this) {
    ExportKind.docx => 'docx',
    ExportKind.txt => 'txt',
    ExportKind.markdown => 'md',
    ExportKind.corrections => 'json',
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
      final font = kind == ExportKind.searchablePdf ? await _exportFont() : null;
      final pdf = await StreamingPdfWriter.open(
        pending.path,
        title: doc.title,
        font: font,
      );
      try {
        for (var index = 0; index < pages.length; index++) {
          if (cancelled?.call() == true) throw StateError('Export cancelled');
          final page = pages[index];
          await pdf.addPage(
            smallPdf ? await _smallJpegOf(page.path, pending.path) : await _jpegOf(page.path),
            pixelWidth: page.width,
            pixelHeight: page.height,
            // Hidden text does not alter the scan; it makes OCR and
            // corrections selectable and searchable.
            lines: kind == ExportKind.searchablePdf ? _textLines(page) : const [],
          );
          progress?.call(index + 1, pages.length);
        }
        await pdf.close();
      } catch (_) {
        await pdf.abandon();
        rethrow;
      }
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
