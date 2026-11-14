/// Page-by-page PDF writer for exports (docs/TECH_UPGRADE_PLAN.md, A4 + E1).
///
/// The `pdf` package builds the whole document in memory before saving; at
/// 150 pages of camera JPEGs that is hundreds of megabytes on a 4 GB phone.
/// This writer appends each page to the file as it goes, so peak memory is
/// one page:
///
/// - page images are JPEG pass-through (DCTDecode): no decode, no re-encode;
/// - recognised text is an invisible layer (text render mode 3), each line
///   stretched to its box (`Tz`) so selection lines up with the printed
///   words;
/// - the Unicode font (Mukta) is embedded once at the end as a Type0 /
///   Identity-H font holding only the glyphs that were used, with a
///   ToUnicode map so copy and search return the original characters.
///
/// Glyphs are the font's nominal ones (no shaping). The text is invisible,
/// so only extraction matters, and extraction is exact Unicode.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

// ---------------------------------------------------------------------------
// TrueType: just enough to map characters, measure them and subset glyf.
// ---------------------------------------------------------------------------

class TrueTypeFont {
  TrueTypeFont._(this._data, this._tables);

  factory TrueTypeFont.parse(Uint8List bytes) {
    final data = ByteData.sublistView(bytes);
    final count = data.getUint16(4);
    final tables = <String, (int, int)>{};
    for (var i = 0; i < count; i++) {
      final at = 12 + i * 16;
      final tag = String.fromCharCodes(bytes.sublist(at, at + 4));
      tables[tag] = (data.getUint32(at + 8), data.getUint32(at + 12));
    }
    for (final tag in ['cmap', 'glyf', 'head', 'hhea', 'hmtx', 'loca', 'maxp']) {
      if (!tables.containsKey(tag)) {
        throw FormatException('Font is missing the $tag table');
      }
    }
    final font = TrueTypeFont._(data, tables);
    font._load();
    return font;
  }

  final ByteData _data;
  final Map<String, (int, int)> _tables;
  late final int unitsPerEm;
  late final int numGlyphs;
  late final bool _longLoca;
  late final List<int> advances;
  late final List<int> _loca;
  final Map<int, int> _cmap = {};
  int ascent = 800, descent = -200;
  List<int> bbox = const [0, -200, 1000, 800];

  int _off(String tag) => _tables[tag]!.$1;

  void _load() {
    final d = _data, head = _off('head');
    unitsPerEm = d.getUint16(head + 18);
    bbox = [
      d.getInt16(head + 36),
      d.getInt16(head + 38),
      d.getInt16(head + 40),
      d.getInt16(head + 42),
    ];
    _longLoca = d.getInt16(head + 50) == 1;
    numGlyphs = d.getUint16(_off('maxp') + 4);
    final hhea = _off('hhea');
    ascent = d.getInt16(hhea + 4);
    descent = d.getInt16(hhea + 6);
    final metrics = d.getUint16(hhea + 34);
    final hmtx = _off('hmtx');
    advances = List.generate(numGlyphs, (g) {
      final i = g < metrics ? g : metrics - 1;
      return d.getUint16(hmtx + i * 4);
    });
    final loca = _off('loca');
    _loca = List.generate(
      numGlyphs + 1,
      (i) => _longLoca ? d.getUint32(loca + i * 4) : d.getUint16(loca + i * 2) * 2,
    );
    _readCmap();
  }

  void _readCmap() {
    final d = _data, cmap = _off('cmap');
    final n = d.getUint16(cmap + 2);
    int? format4, format12;
    for (var i = 0; i < n; i++) {
      final rec = cmap + 4 + i * 8;
      final platform = d.getUint16(rec), encoding = d.getUint16(rec + 2);
      final at = cmap + d.getUint32(rec + 4);
      final format = d.getUint16(at);
      final unicode = platform == 0 || (platform == 3 && (encoding == 1 || encoding == 10));
      if (!unicode) continue;
      if (format == 12) format12 ??= at;
      if (format == 4) format4 ??= at;
    }
    if (format12 != null) {
      final groups = d.getUint32(format12 + 12);
      for (var i = 0; i < groups; i++) {
        final g = format12 + 16 + i * 12;
        final start = d.getUint32(g), end = d.getUint32(g + 4);
        var gid = d.getUint32(g + 8);
        for (var cp = start; cp <= end; cp++) {
          _cmap[cp] = gid++;
        }
      }
      return;
    }
    if (format4 == null) throw const FormatException('Font has no Unicode cmap');
    final at = format4;
    final segments = d.getUint16(at + 6) ~/ 2;
    final ends = at + 14, starts = ends + segments * 2 + 2;
    final deltas = starts + segments * 2, ranges = deltas + segments * 2;
    for (var s = 0; s < segments; s++) {
      final end = d.getUint16(ends + s * 2), start = d.getUint16(starts + s * 2);
      final delta = d.getInt16(deltas + s * 2);
      final rangeAt = ranges + s * 2, range = d.getUint16(rangeAt);
      for (var cp = start; cp <= end && cp != 0xFFFF; cp++) {
        int gid;
        if (range == 0) {
          gid = (cp + delta) & 0xFFFF;
        } else {
          final g = d.getUint16(rangeAt + range + (cp - start) * 2);
          gid = g == 0 ? 0 : (g + delta) & 0xFFFF;
        }
        if (gid != 0) _cmap[cp] = gid;
      }
    }
  }

  /// Nominal glyph for a code point (0 = .notdef).
  int glyph(int codePoint) => _cmap[codePoint] ?? 0;

  /// Components referenced by a composite glyph.
  Iterable<int> _components(int gid) sync* {
    final start = _loca[gid], end = _loca[gid + 1];
    if (end <= start) return;
    final d = _data, glyf = _off('glyf') + start;
    if (d.getInt16(glyf) >= 0) return; // simple glyph
    var at = glyf + 10;
    while (true) {
      final flags = d.getUint16(at);
      yield d.getUint16(at + 2);
      at += 4 + ((flags & 0x0001) != 0 ? 4 : 2);
      if ((flags & 0x0008) != 0) {
        at += 2;
      } else if ((flags & 0x0040) != 0) {
        at += 4;
      } else if ((flags & 0x0080) != 0) {
        at += 8;
      }
      if ((flags & 0x0020) == 0) break;
    }
  }

  /// A font file holding only [used] glyphs (and their components). Glyph
  /// ids are unchanged, so Identity-H codes stay the original glyph ids.
  Uint8List subset(Set<int> used) {
    final keep = <int>{};
    final todo = [0, ...used]; // .notdef is always present
    while (todo.isNotEmpty) {
      final g = todo.removeLast();
      if (g < 0 || g >= numGlyphs || !keep.add(g)) continue;
      todo.addAll(_components(g));
    }
    final source = _data.buffer.asUint8List(_data.offsetInBytes, _data.lengthInBytes);
    final glyfStart = _off('glyf');
    final glyf = BytesBuilder(copy: false);
    final loca = ByteData((numGlyphs + 1) * 4);
    var offset = 0;
    for (var g = 0; g < numGlyphs; g++) {
      loca.setUint32(g * 4, offset);
      if (keep.contains(g)) {
        final a = _loca[g], b = _loca[g + 1];
        if (b > a) {
          glyf.add(source.sublist(glyfStart + a, glyfStart + b));
          offset += b - a;
          final pad = (4 - offset % 4) % 4;
          if (pad > 0) {
            glyf.add(Uint8List(pad));
            offset += pad;
          }
        }
      }
    }
    loca.setUint32(numGlyphs * 4, offset);

    Uint8List table(String tag) {
      final (at, length) = _tables[tag]!;
      return Uint8List.fromList(source.sublist(at, at + length));
    }

    final head = table('head');
    ByteData.sublistView(head)
      ..setUint32(8, 0) // checkSumAdjustment: recomputed by nobody that matters
      ..setInt16(50, 1); // long loca
    final tables = <String, Uint8List>{
      for (final tag in ['cvt ', 'fpgm', 'prep'])
        if (_tables.containsKey(tag)) tag: table(tag),
      'glyf': glyf.toBytes(),
      'head': head,
      'hhea': table('hhea'),
      'hmtx': table('hmtx'),
      'loca': loca.buffer.asUint8List(),
      'maxp': table('maxp'),
    };
    return _sfnt(tables);
  }

  static Uint8List _sfnt(Map<String, Uint8List> tables) {
    final tags = tables.keys.toList()..sort();
    final n = tags.length;
    var power = 1, log = 0;
    while (power * 2 <= n) {
      power *= 2;
      log++;
    }
    final header = ByteData(12 + n * 16)
      ..setUint32(0, 0x00010000)
      ..setUint16(4, n)
      ..setUint16(6, power * 16)
      ..setUint16(8, log)
      ..setUint16(10, n * 16 - power * 16);
    final body = BytesBuilder(copy: false);
    var offset = 12 + n * 16;
    for (var i = 0; i < n; i++) {
      final data = tables[tags[i]]!;
      final padded = Uint8List((data.length + 3) & ~3)..setAll(0, data);
      var sum = 0;
      final view = ByteData.sublistView(padded);
      for (var j = 0; j < padded.length; j += 4) {
        sum = (sum + view.getUint32(j)) & 0xFFFFFFFF;
      }
      final rec = 12 + i * 16;
      for (var k = 0; k < 4; k++) {
        header.setUint8(rec + k, tags[i].codeUnitAt(k));
      }
      header
        ..setUint32(rec + 4, sum)
        ..setUint32(rec + 8, offset)
        ..setUint32(rec + 12, data.length);
      body.add(padded);
      offset += padded.length;
    }
    return (BytesBuilder(copy: false)
          ..add(header.buffer.asUint8List())
          ..add(body.toBytes()))
        .toBytes();
  }
}

// ---------------------------------------------------------------------------
// JPEG header: size and colour model for pass-through embedding.
// ---------------------------------------------------------------------------

class JpegInfo {
  const JpegInfo(this.width, this.height, this.components);
  final int width, height, components;

  /// Null when [bytes] is not a baseline/progressive JPEG.
  static JpegInfo? read(Uint8List bytes) {
    if (bytes.length < 4 || bytes[0] != 0xFF || bytes[1] != 0xD8) return null;
    var at = 2;
    while (at + 4 <= bytes.length) {
      if (bytes[at] != 0xFF) return null;
      final marker = bytes[at + 1];
      if (marker == 0xFF) {
        at++;
        continue;
      }
      if (marker == 0xD8 || (marker >= 0xD0 && marker <= 0xD7) || marker == 0x01) {
        at += 2;
        continue;
      }
      final length = (bytes[at + 2] << 8) | bytes[at + 3];
      final isSof = marker >= 0xC0 && marker <= 0xCF &&
          marker != 0xC4 && marker != 0xC8 && marker != 0xCC;
      if (isSof && at + 9 < bytes.length) {
        final height = (bytes[at + 5] << 8) | bytes[at + 6];
        final width = (bytes[at + 7] << 8) | bytes[at + 8];
        return JpegInfo(width, height, bytes[at + 9]);
      }
      at += 2 + length;
    }
    return null;
  }
}

// ---------------------------------------------------------------------------
// The writer.
// ---------------------------------------------------------------------------

/// One recognised line: text and its box in page-image pixels.
class PdfTextLine {
  const PdfTextLine(this.text, this.left, this.top, this.width, this.height);
  final String text;
  final double left, top, width, height;
}

class StreamingPdfWriter {
  StreamingPdfWriter._(this._file, this._font, this._title);

  /// Starts a PDF at [path]. Pass [font] to allow text layers.
  static Future<StreamingPdfWriter> open(
    String path, {
    required String title,
    TrueTypeFont? font,
  }) async {
    final file = await File(path).open(mode: FileMode.write);
    final writer = StreamingPdfWriter._(file, font, title);
    await writer._raw(latin1.encode('%PDF-1.7\n%âãÏÓ\n'));
    return writer;
  }

  final RandomAccessFile _file;
  final TrueTypeFont? _font;
  final String _title;
  int _position = 0;
  final Map<int, int> _offsets = {};
  int _next = 4; // 1 catalog, 2 pages, 3 font (reserved)
  final List<int> _pages = [];
  final Map<int, int> _glyphToCodePoint = {};
  bool _closed = false;

  static const _catalog = 1, _pagesRef = 2, _fontRef = 3;

  int get pageCount => _pages.length;

  Future<void> _raw(List<int> bytes) async {
    await _file.writeFrom(bytes);
    _position += bytes.length;
  }

  Future<void> _object(int id, String body, [List<int>? stream]) async {
    _offsets[id] = _position;
    final head = StringBuffer('$id 0 obj\n');
    if (stream == null) {
      head.write('$body\nendobj\n');
      await _raw(latin1.encode(head.toString()));
      return;
    }
    head.write('$body\nstream\n');
    await _raw(latin1.encode(head.toString()));
    await _raw(stream);
    await _raw(latin1.encode('\nendstream\nendobj\n'));
  }

  static String _num(double v) {
    if (v.isNaN || v.isInfinite) return '0';
    final s = v.toStringAsFixed(2);
    return s.contains('.') ? s.replaceFirst(RegExp(r'\.?0+$'), '') : s;
  }

  /// Adds one page: [jpeg] fills the page; [lines] (in image pixels of a
  /// [pixelWidth] x [pixelHeight] page) become invisible, selectable text.
  /// The page is 595 pt wide (A4 width) with the image's aspect ratio.
  Future<void> addPage(
    Uint8List jpeg, {
    int? pixelWidth,
    int? pixelHeight,
    List<PdfTextLine> lines = const [],
  }) async {
    if (_closed) throw StateError('PDF already closed');
    final info = JpegInfo.read(jpeg);
    if (info == null) throw const FormatException('Page image is not a JPEG');
    final colour = switch (info.components) {
      1 => '/DeviceGray',
      3 => '/DeviceRGB',
      4 => '/DeviceCMYK /Decode [1 0 1 0 1 0 1 0]',
      _ => throw const FormatException('Unsupported JPEG colour model'),
    };
    final imageId = _next++, contentId = _next++, pageId = _next++;
    await _object(
      imageId,
      '<< /Type /XObject /Subtype /Image /Width ${info.width} '
      '/Height ${info.height} /ColorSpace $colour /BitsPerComponent 8 '
      '/Filter /DCTDecode /Length ${jpeg.length} >>',
      jpeg,
    );

    const pageWidth = 595.0;
    final pageHeight = pageWidth * info.height / info.width;
    final scale = pageWidth / (pixelWidth ?? info.width);
    final content = StringBuffer()
      ..write('q ${_num(pageWidth)} 0 0 ${_num(pageHeight)} 0 0 cm /Im0 Do Q\n');
    final font = _font;
    if (font != null && lines.isNotEmpty) {
      content.write('BT 3 Tr\n');
      for (final line in lines) {
        final runes = line.text.runes.where((r) => r >= 0x20).toList();
        if (runes.isEmpty || line.width <= 0 || line.height <= 0) continue;
        final hex = StringBuffer();
        var advance = 0;
        for (final r in runes) {
          final gid = font.glyph(r);
          if (gid == 0) continue; // no glyph: nothing extractable to place
          _glyphToCodePoint.putIfAbsent(gid, () => r);
          hex.write(gid.toRadixString(16).padLeft(4, '0'));
          advance += font.advances[gid];
        }
        if (advance == 0) continue;
        final size = line.height * scale * 0.8;
        final textWidth = advance * size / font.unitsPerEm;
        final stretch = (100 * line.width * scale / textWidth).clamp(1.0, 2000.0);
        final x = line.left * scale;
        // Baseline near the bottom of the box (descenders below it).
        final y = pageHeight - (line.top + line.height) * scale +
            line.height * scale * 0.2;
        content.write(
          '/F0 ${_num(size)} Tf ${_num(stretch)} Tz '
          '1 0 0 1 ${_num(x)} ${_num(y)} Tm <$hex> Tj\n',
        );
      }
      content.write('ET\n');
    }
    final bytes = latin1.encode(content.toString());
    await _object(contentId, '<< /Length ${bytes.length} >>', bytes);
    final fontResource = font != null ? '/Font << /F0 $_fontRef 0 R >> ' : '';
    await _object(
      pageId,
      '<< /Type /Page /Parent $_pagesRef 0 R '
      '/MediaBox [0 0 ${_num(pageWidth)} ${_num(pageHeight)}] '
      '/Resources << $fontResource/XObject << /Im0 $imageId 0 R >> >> '
      '/Contents $contentId 0 R >>',
    );
    _pages.add(pageId);
  }

  static String _utf16Hex(String text) {
    final out = StringBuffer('FEFF');
    for (final unit in text.codeUnits) {
      out.write(unit.toRadixString(16).padLeft(4, '0'));
    }
    return out.toString().toUpperCase();
  }

  Future<void> _writeFont(TrueTypeFont font) async {
    final cidId = _next++, descriptorId = _next++, fileId = _next++;
    final toUnicodeId = _next++;
    final used = _glyphToCodePoint.keys.toSet();
    final program = font.subset(used);
    const name = 'VSAAAA+Mukta-Regular';
    await _object(
      _fontRef,
      '<< /Type /Font /Subtype /Type0 /BaseFont /$name /Encoding /Identity-H '
      '/DescendantFonts [$cidId 0 R] /ToUnicode $toUnicodeId 0 R >>',
    );
    final widths = StringBuffer();
    for (final gid in used.toList()..sort()) {
      widths.write('$gid [${(font.advances[gid] * 1000 / font.unitsPerEm).round()}] ');
    }
    await _object(
      cidId,
      '<< /Type /Font /Subtype /CIDFontType2 /BaseFont /$name '
      '/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> '
      '/FontDescriptor $descriptorId 0 R /CIDToGIDMap /Identity '
      '/DW 500 /W [$widths] >>',
    );
    final k = 1000 / font.unitsPerEm;
    await _object(
      descriptorId,
      '<< /Type /FontDescriptor /FontName /$name /Flags 4 '
      '/FontBBox [${font.bbox.map((v) => (v * k).round()).join(' ')}] '
      '/ItalicAngle 0 /Ascent ${(font.ascent * k).round()} '
      '/Descent ${(font.descent * k).round()} /CapHeight ${(font.ascent * k).round()} '
      '/StemV 80 /FontFile2 $fileId 0 R >>',
    );
    await _object(
      fileId,
      '<< /Length ${program.length} /Length1 ${program.length} >>',
      program,
    );
    final cmap = StringBuffer(
      '/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n'
      '/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n'
      '/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n'
      '1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n',
    );
    final entries = _glyphToCodePoint.entries.toList()
      ..sort((a, b) => a.key.compareTo(b.key));
    for (var i = 0; i < entries.length; i += 100) {
      final chunk = entries.skip(i).take(100).toList();
      cmap.write('${chunk.length} beginbfchar\n');
      for (final e in chunk) {
        final units = String.fromCharCode(e.value).codeUnits
            .map((u) => u.toRadixString(16).padLeft(4, '0'))
            .join();
        cmap.write('<${e.key.toRadixString(16).padLeft(4, '0')}> <$units>\n');
      }
      cmap.write('endbfchar\n');
    }
    cmap.write('endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n');
    final bytes = latin1.encode(cmap.toString());
    await _object(toUnicodeId, '<< /Length ${bytes.length} >>', bytes);
  }

  /// Writes the font, page tree, catalog and cross-reference table.
  Future<void> close() async {
    if (_closed) return;
    if (_pages.isEmpty) throw StateError('A PDF needs at least one page.');
    final font = _font;
    if (font != null) await _writeFont(font);
    await _object(
      _pagesRef,
      '<< /Type /Pages /Count ${_pages.length} '
      '/Kids [${_pages.map((p) => '$p 0 R').join(' ')}] >>',
    );
    await _object(_catalog, '<< /Type /Catalog /Pages $_pagesRef 0 R >>');
    final infoId = _next++;
    final now = DateTime.now().toUtc();
    String two(int v) => v.toString().padLeft(2, '0');
    final date = 'D:${now.year}${two(now.month)}${two(now.day)}'
        '${two(now.hour)}${two(now.minute)}${two(now.second)}Z';
    await _object(
      infoId,
      '<< /Title <${_utf16Hex(_title)}> /Creator (VeriScript Offline) '
      '/Producer (VeriScript) /CreationDate ($date) >>',
    );
    final xref = _position;
    final size = _next;
    final table = StringBuffer('xref\n0 $size\n0000000000 65535 f \n');
    for (var id = 1; id < size; id++) {
      final offset = _offsets[id];
      table.write(offset == null
          ? '0000000000 65535 f \n'
          : '${offset.toString().padLeft(10, '0')} 00000 n \n');
    }
    table.write(
      'trailer\n<< /Size $size /Root $_catalog 0 R /Info $infoId 0 R >>\n'
      'startxref\n$xref\n%%EOF\n',
    );
    await _raw(latin1.encode(table.toString()));
    await _file.flush();
    await _file.close();
    _closed = true;
  }

  /// Stops without producing a valid PDF (the caller deletes the file).
  Future<void> abandon() async {
    if (_closed) return;
    _closed = true;
    await _file.close();
  }
}
