import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/layout.dart';

/// docs/TECH_UPGRADE_PLAN.md D4: the phone's reading order must match the
/// desktop's measured algorithm exactly. The fixture comes from real pages
/// (two-column papers, receipts, Nepali government PDFs, letterpress) run
/// through the desktop engine; see scripts/build_reading_order_fixture.py.
void main() {
  final fixture =
      jsonDecode(File('test/fixtures/reading_order_parity.json').readAsStringSync())
          as Map<String, dynamic>;
  final cases = (fixture['cases'] as List).cast<Map<String, dynamic>>();

  List<LayoutBox> boxesOf(Map<String, dynamic> c) => [
    for (final t in (c['tokens'] as List).cast<Map<String, dynamic>>())
      LayoutBox(
        t['text'] as String,
        (t['bbox'][0] as num).toInt(),
        (t['bbox'][1] as num).toInt(),
        (t['bbox'][2] as num).toInt(),
        (t['bbox'][3] as num).toInt(),
      ),
  ];

  test('fixture covers reordered and untouched pages', () {
    expect(cases.length, greaterThanOrEqualTo(30));
    final reordered = cases.where((c) {
      final e = (c['expected'] as List).cast<int>();
      return !const ListEquality().equals(e, List.generate(e.length, (i) => i));
    }).length;
    expect(reordered, greaterThanOrEqualTo(10));
    expect(cases.length - reordered, greaterThanOrEqualTo(10));
  });

  for (final c in cases) {
    test('same order as the desktop: ${c['name']}', () {
      expect(readingOrder(boxesOf(c)), (c['expected'] as List).cast<int>());
    });
  }

  test('two columns read left column first, keeping each line', () {
    final lines = <Map<String, dynamic>>[];
    for (var i = 0; i < 7; i++) {
      final y = 100.0 + i * 60;
      lines.add({'text': 'right $i words here', 'bbox': [620.0, y, 480.0 - i * 10, 30.0]});
      lines.add({'text': 'left $i words here', 'bbox': [60.0, y, 470.0 - i * 15, 30.0]});
    }
    final sorted = sortLines(lines).map((l) => l['text']).toList();
    expect(sorted, [
      for (var i = 0; i < 7; i++) 'left $i words here',
      for (var i = 0; i < 7; i++) 'right $i words here',
    ]);
  });

  test('receipt label/value rows keep the engine order', () {
    final lines = <Map<String, dynamic>>[];
    for (var i = 0; i < 10; i++) {
      final y = 100.0 + i * 45;
      lines.add({'text': 'Item name $i', 'bbox': [60.0, y, 360.0, 28.0]});
      lines.add({'text': '1$i.50', 'bbox': [820.0, y, 160.0, 28.0]});
    }
    expect(identical(sortLines(lines).first, lines.first), isTrue);
    expect(sortLines(lines).map((l) => l['text']), lines.map((l) => l['text']));
  });

  test('empty and single-line pages are returned as they are', () {
    expect(readingOrder([]), isEmpty);
    expect(readingOrder([LayoutBox('a', 0, 0, 10, 10)]), [0]);
  });
}

class ListEquality {
  const ListEquality();
  bool equals(List<int> a, List<int> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}
