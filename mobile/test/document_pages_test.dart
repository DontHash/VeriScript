import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/documents.dart';

/// docs/TECH_UPGRADE_PLAN.md E5: move pages into a new document (split) and
/// copy pages from another document (combine). Every working file of a page
/// travels with it, nothing a remaining page uses is deleted, and saved
/// documents reload intact.
void main() {
  late Directory root;
  late DocumentStore store;

  setUp(() async {
    root = await Directory.systemTemp.createTemp('vs-pages-');
    store = DocumentStore(root);
  });
  tearDown(() => root.delete(recursive: true));

  Future<ScanDocument> docWith(String title, List<String> ids) async {
    final doc = await store.create(title);
    final dir = store.directory(doc);
    for (final id in ids) {
      for (final name in ['original_$id.jpg', 'source_$id.jpg', 'page_$id.jpg', 'edit_${id}_99.jpg']) {
        await File('$dir/$name').writeAsString('$title $name');
      }
      doc.pages.add(ScanPage(
        id: id,
        source: '$dir/source_$id.jpg',
        path: '$dir/edit_${id}_99.jpg',
        recognized: true,
        lines: [
          {'text': 'page $id', 'original': 'paqe $id'},
        ],
        previousVersion: {'path': '$dir/page_$id.jpg', 'width': 1, 'height': 1,
          'lines': [], 'recognized': false, 'note': ''},
      ));
    }
    await File('$dir/report_123.pdf').writeAsString('an export');
    await store.save(doc);
    return doc;
  }

  List<String> names(ScanDocument doc) =>
      Directory(store.directory(doc)).listSync().map((f) => f.uri.pathSegments.last).toList()..sort();

  test('moving pages to a new document takes their files and leaves the rest', () async {
    final doc = await docWith('Ward 7', ['11', '22', '33']);
    final progress = <int>[];
    final created = await store.movePagesToNew(doc, [doc.pages[1], doc.pages[2]], 'Ward 7 (2)',
        progress: (done, _) => progress.add(done));
    expect(progress, [1, 2]);
    expect(doc.pages.map((p) => p.id), ['11']);
    expect(names(doc), ['document.json', 'edit_11_99.jpg', 'original_11.jpg', 'page_11.jpg',
        'report_123.pdf', 'source_11.jpg']);
    expect(created.pages.map((p) => p.text), ['page 22', 'page 33']);
    for (final p in created.pages) {
      expect(p.path, startsWith(store.directory(created)));
      expect(await File(p.path).readAsString(), startsWith('Ward 7 edit_'));
      expect(await File(p.source).exists(), isTrue);
      expect(await File(p.previousVersion!['path'] as String).exists(), isTrue);
      expect(p.lines.single['original'], startsWith('paqe'));
    }
    expect(names(created).where((n) => n.startsWith('original_')).length, 2);
    // Both documents reload from disk as they are in memory.
    final reloaded = {for (final d in await store.list()) d.id: d};
    expect(reloaded[doc.id]!.pages.map((p) => p.id), ['11']);
    expect(reloaded[created.id]!.pages.map((p) => p.path), created.pages.map((p) => p.path));
  });

  test('moving all or no pages is refused', () async {
    final doc = await docWith('A', ['1', '2']);
    expect(() => store.movePagesToNew(doc, doc.pages.toList(), 'B'), throwsStateError);
    expect(() => store.movePagesToNew(doc, [], 'B'), throwsStateError);
    expect(doc.pages.length, 2);
  });

  test('copying pages from another document leaves the source alone', () async {
    final a = await docWith('Receipts', ['1']);
    final b = await docWith('More receipts', ['2', '3']);
    final before = names(b);
    await store.copyPages(b, b.pages, a);
    expect(a.pages.map((p) => p.text), ['page 1', 'page 2', 'page 3']);
    expect(names(b), before);
    expect(b.pages.length, 2);
    // The same pages can be added twice: copies get fresh ids and file names.
    await store.copyPages(b, b.pages, a);
    expect(a.pages.map((p) => p.id).toSet().length, 5);
    expect(a.pages.map((p) => p.path).toSet().length, 5);
    for (final p in a.pages) {
      expect(await File(p.path).exists(), isTrue);
    }
  });

  test('combining keeps to the page limit and refuses the same document', () async {
    final a = await docWith('A', ['1']);
    final big = await docWith('Big', [for (var i = 100; i < 100 + DocumentStore.maxPages; i++) '$i']);
    expect(() => store.copyPages(big, big.pages, a), throwsA(isA<StateError>()
        .having((e) => e.message, 'message', contains('up to 150'))));
    expect(a.pages.length, 1);
    expect(() => store.copyPages(a, a.pages, a), throwsStateError);
  });
}
