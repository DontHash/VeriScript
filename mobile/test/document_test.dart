import 'dart:convert';
import 'dart:io';
import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/exports.dart';
import 'package:veriscript_mobile/processing.dart';

void main() {
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
