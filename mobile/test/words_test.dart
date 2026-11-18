import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/exports.dart';
import 'package:veriscript_mobile/processing.dart';

/// docs/TECH_UPGRADE_PLAN.md D5: words are stored with their boxes; review
/// and the PDF text layer use them while they still spell the line.
void main() {
  Map<String, dynamic> line(String text, List<(String, double)> words) => {
    'text': text,
    'bbox': [0, 0, 300, 20],
    'words': [
      for (var i = 0; i < words.length; i++)
        {
          'text': words[i].$1,
          'confidence': words[i].$2,
          'bbox': [i * 100.0, 0, 90.0, 20.0],
        },
    ],
  };

  test('numbers first, then the least confident words', () {
    final lines = [
      line('मिति २०८१ सालको', [('मिति', .95), ('२०८१', .99), ('सालको', .5)]),
      line('kept words', [('kept', .99), ('words', .7)]),
    ];
    final queue = wordsToCheck(lines).map((r) => r.word['text']).toList();
    expect(queue, ['२०८१', 'सालको', 'words']);
  });

  test('correcting a word rewrites its line and leaves the queue', () {
    final lines = [
      line('rent 1O0', [('rent', .99), ('1O0', .6)]),
    ];
    final ref = wordsToCheck(lines).single;
    correctWord(ref, '100');
    expect(lines.single['text'], 'rent 100');
    expect(wordsToCheck(lines), isEmpty);
  });

  test('a line corrected as a whole falls back to one run', () {
    final l = line('rent 100', [('rent', .99), ('100', .6)]);
    expect(lineWords(l)!.map((w) => w.text), ['rent', '100']);
    expect(lineWords(l)![1].left, 100);
    l['text'] = 'rent 1,000';
    expect(lineWords(l), isNull);
    expect(wordsToCheck([l]), isEmpty);
    final page = ScanPage(id: '1', source: 's', path: 'p', lines: [l]);
    expect(textRuns(page).single.text, 'rent 1,000');
  });

  test('lines without words keep their line box', () {
    final page = ScanPage(
      id: '1',
      source: 's',
      path: 'p',
      lines: [
        {
          'text': 'old line',
          'bbox': [1, 2, 3, 4],
        },
      ],
    );
    expect(textRuns(page).single.width, 3);
  });
}
