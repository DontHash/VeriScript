import 'dart:convert';
import 'dart:io';
import 'dart:math' show max;

import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import 'capture_quality.dart';

const native = MethodChannel('veriscript/offline');

/// Native bounds + luma-sample validation for a just-captured JPEG.
Future<CaptureInfo> readCaptureInfo(String path) async {
  final info = await native.invokeMapMethod<String, dynamic>('jpegInfo', {
    'path': path,
  });
  if (info == null) throw StateError('No capture metadata was returned.');
  return CaptureInfo.fromMap(info);
}

/// Native blur and glare measures for a just-captured photo (C3).
Future<CaptureQuality> readCaptureQuality(String path) async {
  final map = await native.invokeMapMethod<String, dynamic>('captureQuality', {
    'path': path,
  });
  if (map == null) throw StateError('No capture quality was returned.');
  return CaptureQuality.fromMap(map);
}

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
    this.previousVersion,
  });
  final String id;
  final String source;
  String path;
  bool included;
  int width, height;
  List<Map<String, dynamic>> lines;
  bool recognized;
  String note;
  Map<String, dynamic>? previousVersion;
  // Keep image geometry and OCR together: old boxes cannot be applied to a crop.
  Map<String, dynamic> snapshot() => jsonDecode(
    jsonEncode({
      'path': path,
      'width': width,
      'height': height,
      'lines': lines,
      'recognized': recognized,
      'note': note,
    }),
  );
  void applySnapshot(Map<String, dynamic> value) {
    path = value['path'];
    width = value['width'];
    height = value['height'];
    lines = (value['lines'] as List)
        .map((line) => Map<String, dynamic>.from(line))
        .toList();
    recognized = value['recognized'];
    note = value['note'];
  }

  void protectText() {
    if (recognized && lines.isNotEmpty) previousVersion = snapshot();
  }

  void restorePreviousVersion() {
    final value = previousVersion;
    if (value == null) return;
    applySnapshot(value);
    previousVersion = null;
  }

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
    'previousVersion': previousVersion,
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
    previousVersion: j['previousVersion'] == null
        ? null
        : Map<String, dynamic>.from(j['previousVersion']),
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
    this.folder = '',
  });
  final String id;
  String title;
  String folder;
  bool matches(String query) {
    if (query.trim().isEmpty) return true;
    final terms = query.trim().toLowerCase().split(RegExp(r'\s+'));
    final content = '$title\n$folder\n${pages.map((p) => p.text).join('\n')}'
        .toLowerCase();
    return terms.every(content.contains);
  }

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
    'folder': folder,
  };
  factory ScanDocument.fromJson(Map<String, dynamic> j) => ScanDocument(
    id: j['id'],
    title: j['title'],
    pages: (j['pages'] as List)
        .map((p) => ScanPage.fromJson(Map<String, dynamic>.from(p)))
        .toList(),
    exports: List<String>.from(j['exports'] ?? []),
    warnings: List<String>.from(j['warnings'] ?? []),
    folder: j['folder'] ?? '',
  );
}

/// One app-private directory per document. Persist after each page, not only
/// on exit, so interrupted batches can be recovered from the Files screen.
///
/// `document.json` stores files inside the document's own folder as
/// `doc:<name>` rather than absolute paths (schema 2), so a restored backup
/// or a moved app-data folder still finds every page. Older absolute paths
/// are re-homed by file name when the file is in the document's folder.
class DocumentStore {
  DocumentStore(this.root);
  final Directory root;

  /// Version of the `document.json` layout this build writes.
  static const schemaVersion = 2;
  static const _local = 'doc:';

  static final _separator = RegExp(r'[\\/]');
  static String _baseName(String path) => path.split(_separator).last;

  /// In-memory absolute path → stored form.
  static String packPath(String dir, String path) =>
      path.startsWith('$dir/') ? '$_local${path.substring(dir.length + 1)}' : path;

  /// Stored form → absolute path in this document's folder.
  static String unpackPath(String dir, String path) {
    if (path.startsWith(_local)) return '$dir/${path.substring(_local.length)}';
    // Schema 1 wrote absolute paths. After a backup restore or a storage
    // move they point at an old root; the file itself is in `dir`.
    if (_separator.hasMatch(path) && !File(path).existsSync()) {
      final rehomed = '$dir/${_baseName(path)}';
      if (File(rehomed).existsSync()) return rehomed;
    }
    return path;
  }

  /// Apply [f] to every file path in a serialized document.
  static Map<String, dynamic> mapPaths(
    Map<String, dynamic> json,
    String Function(String) f,
  ) {
    String? one(Object? v) => v is String ? f(v) : null;
    for (final raw in json['pages'] as List? ?? const []) {
      final page = raw as Map;
      for (final key in ['path', 'source']) {
        final v = one(page[key]);
        if (v != null) page[key] = v;
      }
      final previous = page['previousVersion'];
      if (previous is Map) {
        final v = one(previous['path']);
        if (v != null) previous['path'] = v;
      }
    }
    final exports = json['exports'];
    if (exports is List) {
      json['exports'] = exports.map((e) => one(e) ?? e).toList();
    }
    return json;
  }
  Future<void> _writes = Future.value();
  static Future<DocumentStore> open() async {
    final base = await getApplicationDocumentsDirectory();
    final root = Directory('${base.path}/documents');
    await root.create(recursive: true);
    return DocumentStore(root);
  }

  String directory(ScanDocument doc) {
    if (!RegExp(r'^[a-zA-Z0-9_-]+$').hasMatch(doc.id)) {
      throw ArgumentError('Invalid document identifier');
    }
    return '${root.path}/${doc.id}';
  }

  /// Only delete the app-owned document directory, never imported source paths.
  Future<void> delete(ScanDocument doc) {
    final path = directory(doc);
    final next = _writes.then((_) async {
      final type = await FileSystemEntity.type(path, followLinks: false);
      if (type == FileSystemEntityType.notFound) return;
      if (type != FileSystemEntityType.directory) {
        throw StateError('Document directory is not a regular directory');
      }
      await Directory(path).delete(recursive: true);
    });
    _writes = next.catchError((Object error) {});
    return next;
  }

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
    final dir = directory(doc);
    final json = mapPaths(
      jsonDecode(jsonEncode(doc.toJson())) as Map<String, dynamic>,
      (p) => packPath(dir, p),
    )..['schemaVersion'] = schemaVersion;
    final snapshot = jsonEncode(json);
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
    await for (final entry in root.list(followLinks: false)) {
      if (entry is! Directory) continue;
      final file = File('${entry.path}/document.json');
      final pending = File('${file.path}.pending');
      // A crash between writing and renaming must not hide an existing draft.
      for (final candidate in [file, pending]) {
        if (!await candidate.exists()) continue;
        try {
          // Same form as directory(doc), which is how paths were packed.
          final dir = '${root.path}/${_baseName(entry.path)}';
          final json = jsonDecode(await candidate.readAsString());
          if (json is! Map<String, dynamic>) continue;
          // `schemaVersion` absent = 1 (absolute paths); migrations key on it.
          final doc = ScanDocument.fromJson(
            mapPaths(json, (p) => unpackPath(dir, p)),
          );
          if (doc.id !=
              entry.uri.pathSegments.where((s) => s.isNotEmpty).last) {
            break;
          }
          docs.add(doc);
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

  /// Pages per document (imports, video and combining all keep to it).
  static const maxPages = 150;

  /// Last id handed to a copied page: ids stay unique within a burst.
  static int _lastId = 0;

  /// Files in [dir] that belong to [page]: the ones its record points at and
  /// every working copy named after its id (original_, source_, page_,
  /// aligned_, enhanced_, `edit_<id>_...`).
  Future<Set<String>> _pageFiles(String dir, ScanPage page) async {
    final files = <String>{};
    for (final p in [page.path, page.source, page.previousVersion?['path']]) {
      if (p is String && p.startsWith('$dir/') && await File(p).exists()) {
        files.add(p);
      }
    }
    final named = RegExp('_${RegExp.escape(page.id)}[._]');
    await for (final e in Directory(dir).list(followLinks: false)) {
      // Same form as stored paths ('$dir/name'), whatever separator the
      // platform lists with, so a file is never collected twice.
      final name = _baseName(e.path);
      if (e is File && named.hasMatch(name)) files.add('$dir/$name');
    }
    return files;
  }

  /// Copy [page] and its files from folder [from] into [to] under a new id,
  /// so the same page can be copied more than once without clashing.
  Future<ScanPage> _copyPage(ScanPage page, String from, String to) async {
    final id = '${_lastId = max(_lastId + 1, DateTime.now().microsecondsSinceEpoch)}';
    final named = RegExp('_${RegExp.escape(page.id)}(?=[._])');
    final moved = <String, String>{};
    for (final f in await _pageFiles(from, page)) {
      final relative = f.substring(from.length + 1);
      final target = '$to/${relative.replaceAll(named, '_$id')}';
      if (await File(target).exists()) {
        throw StateError('A page file already exists in the other document.');
      }
      await File(target).parent.create(recursive: true);
      await File(f).copy(target);
      moved[f] = target;
    }
    final json = mapPaths(
      {
        'pages': [jsonDecode(jsonEncode(page.toJson()))],
      },
      (p) => moved[p] ?? p,
    );
    final copy = Map<String, dynamic>.from((json['pages'] as List).single);
    copy['id'] = id;
    return ScanPage.fromJson(copy);
  }

  /// Append copies of [pages] (from [source]) to [target]. The source is left
  /// as it is; the user deletes it if they no longer want it.
  Future<void> copyPages(
    ScanDocument source,
    List<ScanPage> pages,
    ScanDocument target, {
    void Function(int, int)? progress,
  }) async {
    if (identical(source, target) || source.id == target.id) {
      throw StateError('Choose a different document.');
    }
    if (target.pages.length + pages.length > maxPages) {
      throw StateError(
        'That would make ${target.pages.length + pages.length} pages; a document holds up to $maxPages.',
      );
    }
    final from = directory(source), to = directory(target);
    for (var i = 0; i < pages.length; i++) {
      target.pages.add(await _copyPage(pages[i], from, to));
      // Save after each page: an interrupted copy keeps what was copied.
      await save(target);
      progress?.call(i + 1, pages.length);
    }
  }

  /// Move [pages] of [doc] into a new document called [title]. The new
  /// document is saved before anything is removed from [doc], so a crash in
  /// between leaves the pages in both rather than in neither.
  Future<ScanDocument> movePagesToNew(
    ScanDocument doc,
    List<ScanPage> pages,
    String title, {
    void Function(int, int)? progress,
  }) async {
    if (pages.isEmpty || pages.length >= doc.pages.length) {
      throw StateError('Select some pages, but not all of them, to move.');
    }
    final created = await create(title);
    created.folder = doc.folder;
    await copyPages(doc, pages, created, progress: progress);
    final dir = directory(doc);
    final leaving = pages.map((p) => p.id).toSet();
    final files = <String>{};
    for (final p in pages) {
      files.addAll(await _pageFiles(dir, p));
    }
    doc.pages.removeWhere((p) => leaving.contains(p.id));
    await save(doc);
    // Never delete a file a remaining page still uses.
    for (final p in doc.pages) {
      files.removeAll(await _pageFiles(dir, p));
    }
    for (final f in files) {
      try {
        await File(f).delete();
      } catch (_) {}
    }
    return created;
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
