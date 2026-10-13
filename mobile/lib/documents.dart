import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

const native = MethodChannel('veriscript/offline');

class ScanPage {
  ScanPage({
    required this.id,
    required this.source,
    required this.path,
    this.included = true,
    this.width = 1,
    this.height = 1,
    this.lines = const [],
    this.recognized = false,
    this.note = '',
  });
  final String id;
  final String source;
  String path;
  bool included;
  int width, height;
  List<Map<String, dynamic>> lines;
  bool recognized;
  String note;
  String get text => lines.map((line) => line['text'] as String).join('\n');
  Map<String, dynamic> toJson() => {
    'id': id,
    'source': source,
    'path': path,
    'included': included,
    'width': width,
    'height': height,
    'lines': lines,
    'recognized': recognized,
    'note': note,
  };
  factory ScanPage.fromJson(Map<String, dynamic> j) => ScanPage(
    id: j['id'],
    source: j['source'],
    path: j['path'],
    included: j['included'],
    width: j['width'],
    height: j['height'],
    recognized: j['recognized'],
    note: j['note'] ?? '',
    lines: (j['lines'] as List)
        .map((e) => Map<String, dynamic>.from(e))
        .toList(),
  );
  void clearText() {
    lines = [];
    recognized = false;
  }
}

class ScanDocument {
  ScanDocument({
    required this.id,
    required this.title,
    required this.pages,
    this.exports = const [],
    this.warnings = const [],
  });
  final String id;
  String title;
  final List<ScanPage> pages;
  List<String> exports;
  List<String> warnings;
  Iterable<ScanPage> get selected => pages.where((p) => p.included);
  Map<String, dynamic> toJson() => {
    'id': id,
    'title': title,
    'pages': pages.map((p) => p.toJson()).toList(),
    'exports': exports,
    'warnings': warnings,
  };
  factory ScanDocument.fromJson(Map<String, dynamic> j) => ScanDocument(
    id: j['id'],
    title: j['title'],
    pages: (j['pages'] as List)
        .map((p) => ScanPage.fromJson(Map<String, dynamic>.from(p)))
        .toList(),
    exports: List<String>.from(j['exports'] ?? []),
    warnings: List<String>.from(j['warnings'] ?? []),
  );
}

/// One app-private directory per document. Persist after each page, not only
/// on exit, so interrupted batches can be recovered from the Files screen.
class DocumentStore {
  DocumentStore(this.root);
  final Directory root;
  Future<void> _writes = Future.value();
  static Future<DocumentStore> open() async {
    final base = await getApplicationDocumentsDirectory();
    final root = Directory('${base.path}/documents');
    await root.create(recursive: true);
    return DocumentStore(root);
  }

  String directory(ScanDocument doc) => '${root.path}/${doc.id}';
  Future<ScanDocument> create(String title) async {
    final doc = ScanDocument(
      id: DateTime.now().microsecondsSinceEpoch.toString(),
      title: title,
      pages: [],
    );
    await Directory(directory(doc)).create(recursive: true);
    await save(doc);
    return doc;
  }

  Future<void> save(ScanDocument doc) {
    final snapshot = jsonEncode(doc.toJson());
    final next = _writes.then((_) async {
      final file = File('${directory(doc)}/document.json');
      final pending = File('${file.path}.pending');
      await pending.writeAsString(snapshot, flush: true);
      await pending.rename(file.path);
    });
    _writes = next.catchError((Object error) {});
    return next;
  }

  Future<List<ScanDocument>> list() async {
    final docs = <ScanDocument>[];
    await for (final entry in root.list()) {
      if (entry is! Directory) continue;
      final file = File('${entry.path}/document.json');
      final pending = File('${file.path}.pending');
      // A crash between writing and renaming must not hide an existing draft.
      for (final candidate in [file, pending]) {
        if (!await candidate.exists()) continue;
        try {
          docs.add(
            ScanDocument.fromJson(jsonDecode(await candidate.readAsString())),
          );
          break;
        } on FormatException {
          continue;
        } on TypeError {
          continue;
        }
      }
    }
    docs.sort((a, b) => b.id.compareTo(a.id));
    return docs;
  }

  Future<ScanPage> importImage(
    ScanDocument doc,
    String path, {
    bool align = true,
    bool enhance = true,
  }) async {
    final id = DateTime.now().microsecondsSinceEpoch.toString();
    final dir = directory(doc);
    // Preserve imported/captured original separately from all transformations.
    final original = await File(path).copy(
      '$dir/original_$id${path.toLowerCase().endsWith('.png') ? '.png' : '.jpg'}',
    );
    final normalized = await native.invokeMapMethod<String, dynamic>(
      'normalize',
      {'path': original.path, 'out': '$dir/source_$id.jpg'},
    );
    final source = normalized!['path'] as String;
    var restored = align
        ? await native.invokeMapMethod<String, dynamic>('restore', {
            'path': source,
            'out': '$dir/page_$id.jpg',
          })
        : normalized;
    if (enhance) {
      restored = await native.invokeMapMethod<String, dynamic>('enhance', {
        'path': restored!['path'],
        'out': '$dir/enhanced_$id.jpg',
      });
    }
    final page = ScanPage(
      id: id,
      source: source,
      path: restored!['path'],
      width: restored['width'],
      height: restored['height'],
      note: restored['note'] ?? '',
    );
    doc.pages.add(page);
    await save(doc);
    return page;
  }
}
