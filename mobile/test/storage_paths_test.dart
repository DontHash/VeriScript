import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/documents.dart';

/// docs/TECH_UPGRADE_PLAN.md A5: document.json must survive a moved
/// app-data folder (backup restore, storage migration).
void main() {
  Future<(Directory, DocumentStore, ScanDocument)> draft() async {
    final root = await Directory.systemTemp.createTemp('veriscript-paths-');
    addTearDown(() async {
      if (await root.exists()) await root.delete(recursive: true);
    });
    final store = DocumentStore(root);
    final doc = await store.create('Receipts');
    final dir = store.directory(doc);
    for (final name in ['page_1.jpg', 'source_1.jpg', 'old_1.jpg', 'x.pdf']) {
      await File('$dir/$name').writeAsBytes([1, 2, 3]);
    }
    doc.pages.add(
      ScanPage(
        id: '1',
        source: '$dir/source_1.jpg',
        path: '$dir/page_1.jpg',
        previousVersion: {'path': '$dir/old_1.jpg', 'width': 1, 'height': 1},
      ),
    );
    doc.exports = ['$dir/x.pdf'];
    await store.save(doc);
    return (root, store, doc);
  }

  test('paths inside the document folder are stored relative', () async {
    final (_, store, doc) = await draft();
    final raw = jsonDecode(
      await File('${store.directory(doc)}/document.json').readAsString(),
    );
    expect(raw['schemaVersion'], DocumentStore.schemaVersion);
    final page = raw['pages'][0];
    expect(page['path'], 'doc:page_1.jpg');
    expect(page['source'], 'doc:source_1.jpg');
    expect(page['previousVersion']['path'], 'doc:old_1.jpg');
    expect(raw['exports'], ['doc:x.pdf']);
    // In memory the paths stay absolute and usable.
    final loaded = (await store.list()).single;
    expect(loaded.pages.single.path, '${store.directory(doc)}/page_1.jpg');
    expect(File(loaded.pages.single.path).existsSync(), isTrue);
  });

  test('a moved app-data folder still finds every file', () async {
    final (root, _, doc) = await draft();
    final moved = Directory('${root.path}_moved');
    await root.rename(moved.path);
    addTearDown(() => moved.delete(recursive: true));
    final store = DocumentStore(moved);
    final page = (await store.list()).single.pages.single;
    expect(page.path, '${moved.path}/${doc.id}/page_1.jpg');
    expect(File(page.path).existsSync(), isTrue);
    expect(File(page.source).existsSync(), isTrue);
    expect(File(page.previousVersion!['path']).existsSync(), isTrue);
  });

  test('schema 1 absolute paths from an old root are re-homed', () async {
    final (root, store, doc) = await draft();
    final file = File('${store.directory(doc)}/document.json');
    final json = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
    // What an older build wrote, under a storage root that no longer exists.
    DocumentStore.mapPaths(
      json,
      (p) => p.startsWith('doc:')
          ? '/data/user/0/old.root/documents/${doc.id}/${p.substring(4)}'
          : p,
    ).remove('schemaVersion');
    await file.writeAsString(jsonEncode(json));

    final loaded = (await store.list()).single;
    final page = loaded.pages.single;
    expect(page.path, '${store.directory(doc)}/page_1.jpg');
    expect(loaded.exports.single, '${store.directory(doc)}/x.pdf');
    // Saving upgrades the file to schema 2.
    await store.save(loaded);
    final upgraded = jsonDecode(await file.readAsString());
    expect(upgraded['schemaVersion'], 2);
    expect(upgraded['pages'][0]['path'], 'doc:page_1.jpg');
    expect(root.existsSync(), isTrue);
  });

  test('paths outside the folder are left alone', () {
    expect(DocumentStore.packPath('/a/doc', '/elsewhere/x.jpg'), '/elsewhere/x.jpg');
    expect(DocumentStore.unpackPath('/a/doc', 'x.jpg'), 'x.jpg');
    // A legacy path whose file is genuinely gone stays as it was.
    expect(
      DocumentStore.unpackPath('/a/doc', '/gone/root/missing.jpg'),
      '/gone/root/missing.jpg',
    );
  });
}
