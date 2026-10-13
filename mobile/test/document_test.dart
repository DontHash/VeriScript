import 'dart:convert';
import 'dart:io';
import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/exports.dart';
import 'package:veriscript_mobile/processing.dart';

void main() {
  test(
    'Previous version survives reload and restores image geometry with corrections',
    () async {
      final root = await Directory.systemTemp.createTemp(
        'veriscript-recovery-',
      );
      addTearDown(() => root.delete(recursive: true));
      final store = DocumentStore(root);
      final doc = await store.create('Protected');
      final page = ScanPage(
        id: 'a',
        source: 'original',
        path: 'reviewed.jpg',
        width: 900,
        height: 1200,
        recognized: true,
        lines: [
          {
            'text': 'Total १२३',
            'original': 'Total १२८',
            'reviewed': true,
            'bbox': [10, 20, 30, 40],
          },
        ],
      );
      doc.pages.add(page);
      page.protectText();
      page.lines.single['text'] = 'mutated';
      (page.lines.single['bbox'] as List)[0] = 999;
      page.path = 'cropped.jpg';
      page.width = 200;
      page.clearText();
      // Further edits to unread images must not discard the protected text.
      page.protectText();
      page.recognized = true; // A failed reading with no lines keeps recovery.
      page.protectText();
      await store.save(doc);
      final reloaded = (await store.list()).single.pages.single;
      reloaded.restorePreviousVersion();
      expect(reloaded.path, 'reviewed.jpg');
      expect(reloaded.width, 900);
      expect(reloaded.height, 1200);
      expect(reloaded.text, 'Total १२३');
      expect(reloaded.lines.single['original'], 'Total १२८');
      expect(reloaded.lines.single['reviewed'], true);
      expect(reloaded.lines.single['bbox'], [10, 20, 30, 40]);
      expect(reloaded.previousVersion, isNull);
    },
  );
  test(
    'Legacy drafts load and search includes corrected Unicode text and folder',
    () {
      final doc = ScanDocument(
        id: 'old',
        title: 'Book',
        pages: [
          ScanPage(
            id: 'a',
            source: 'a',
            path: 'a',
            lines: [
              {'text': 'नेपाल १२३'},
            ],
          ),
        ],
      );
      final legacy = doc.toJson()..remove('folder');
      (legacy['pages'] as List).single.remove('previousVersion');
      final restored = ScanDocument.fromJson(legacy);
      expect(restored.folder, '');
      expect(restored.pages.single.previousVersion, isNull);
      restored.folder = 'Study';
      expect(restored.matches('  BOOK नेपाल '), isTrue);
      expect(restored.matches('study १२३'), isTrue);
      expect(restored.matches('missing'), isFalse);
      expect(restored.matches(''), isTrue);
    },
  );
  test(
    'Deletion waits for writes, removes only its directory, and cannot resurrect a draft',
    () async {
      final root = await Directory.systemTemp.createTemp('veriscript-delete-');
      addTearDown(() => root.delete(recursive: true));
      final store = DocumentStore(root);
      final doc = await store.create('Remove');
      final keep = await store.create('Keep');
      final original = await File(
        '${root.path}/imported.jpg',
      ).writeAsString('keep source');
      doc.pages.add(
        ScanPage(id: 'p', source: original.path, path: original.path),
      );
      final write = store.save(doc);
      final remove = store.delete(doc);
      await Future.wait([write, remove]);
      expect(await Directory(store.directory(doc)).exists(), isFalse);
      expect(await original.readAsString(), 'keep source');
      expect((await store.list()).single.id, keep.id);
      await expectLater(store.save(doc), throwsA(isA<FileSystemException>()));
      await store.save(keep);
      expect((await store.list()).single.title, 'Keep');
      final unsafe = ScanDocument(id: '../outside', title: 'Unsafe', pages: []);
      expect(() => store.delete(unsafe), throwsArgumentError);
      expect(await Directory(store.directory(keep)).exists(), isTrue);
    },
  );
  test(
    'Orientation scoring distinguishes upright from readable upside-down text',
    () {
      expect(orientationWeight(0, 300, 30), 1);
      expect(orientationWeight(180, 300, 30), .1);
      expect(orientationWeight(-180, 300, 30), .1);
      expect(orientationWeight(90, 30, 300), .1);
      expect(orientationWeight(null, 30, 300), .25);
    },
  );
  test(
    'Digit checks preserve group boundaries and compare scripts without guessing',
    () {
      expect(compareDigitReadings('Total १२३', 'Total 123'), 'matched');
      expect(compareDigitReadings('Total १२३', 'Total १२८'), 'conflict');
      expect(compareDigitReadings('1/23', '12/3'), 'conflict');
      expect(compareDigitReadings('001', '1'), 'conflict');
      expect(compareDigitReadings('१२३', 'Unreadable'), 'unreadable');
      expect(
        reviewLabel({'text': '१२३', 'digitCheck': 'matched'}),
        contains('confirm'),
      );
      expect(
        needsReview({
          'text': '१२३',
          'confidence': .99,
          'digitCheck': 'matched',
        }),
        true,
      );
    },
  );
  test(
    'Word export preserves Unicode, order, XML escaping and page breaks',
    () {
      final zip = ZipDecoder().decodeBytes(
        wordDocument('किताब & notes', ['पहिलो १२३ <test>', 'Second page']),
      );
      final xml = utf8.decode(
        zip.find('word/document.xml')!.content as List<int>,
      );
      expect(xml, contains('किताब &amp; notes'));
      expect(xml, contains('पहिलो १२३ &lt;test&gt;'));
      expect(xml.indexOf('पहिलो'), lessThan(xml.indexOf('Second page')));
      expect(RegExp('w:type="page"').allMatches(xml), hasLength(1));
      expect(zip.find('[Content_Types].xml'), isNotNull);
    },
  );
  test(
    'Concurrent draft writes preserve final order, exclusions and corrections',
    () async {
      final root = await Directory.systemTemp.createTemp('veriscript-test-');
      addTearDown(() => root.delete(recursive: true));
      final store = DocumentStore(root);
      final doc = await store.create('Draft');
      doc.pages.add(
        ScanPage(
          id: 'a',
          source: 'source-a',
          path: 'a',
          recognized: true,
          lines: [
            {'text': '१२३', 'original': '१२८', 'reviewed': true},
          ],
        ),
      );
      final first = store.save(doc);
      doc.pages.add(
        ScanPage(id: 'b', source: 'source-b', path: 'b', included: false),
      );
      final second = store.save(doc);
      doc.pages.insert(0, doc.pages.removeLast());
      final last = store.save(doc);
      await Future.wait([first, second, last]);
      final restored = (await store.list()).single;
      expect(restored.pages.map((p) => p.id), ['b', 'a']);
      expect(restored.selected.map((p) => p.id), ['a']);
      expect(restored.selected.single.text, '१२३');
      expect(restored.selected.single.lines.single['original'], '१२८');
    },
  );
  test('Uncertain OCR and numbers require review until confirmed', () {
    expect(needsReview({'text': '१२३', 'confidence': .99}), isTrue);
    expect(needsReview({'text': 'Hello', 'confidence': null}), isTrue);
    expect(needsReview({'text': 'Hello', 'confidence': .95}), isFalse);
    expect(
      needsReview({'text': '१२३', 'confidence': null, 'reviewed': true}),
      isFalse,
    );
  });
}
