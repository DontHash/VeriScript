/// Reading order for recognised lines (docs/TECH_UPGRADE_PLAN.md, D4).
///
/// A line-by-line port of the desktop's measured algorithm in
/// `veriscript/document/layout.py`. Every threshold there encodes a measured
/// failure (receipt value columns, invoice tables, letterpress title pages),
/// so the port keeps them all and must reproduce the desktop's order exactly:
/// `test/layout_test.dart` checks that against
/// `test/fixtures/reading_order_parity.json`, built from real pages by
/// `scripts/build_reading_order_fixture.py`.
///
/// In short: a confident vertical gutter (crossed by at most 5% of boxes,
/// text on both sides, ragged right, not numbers) means two columns, read
/// left then right; full-width lines split the page into bands that are
/// judged separately; table grids are read cell by cell, dense tables row
/// by row. Without any of those the engine's order is returned unchanged.
library;

import 'dart:math';

class LayoutBox {
  LayoutBox(this.text, this.x0, this.y0, this.x1, this.y1);
  final String text;
  final int x0, y0, x1, y1;
  double get cx => (x0 + x1) / 2.0;
  double get cy => (y0 + y1) / 2.0;
}

const _coverageLimit = 0.05;
const _gutterMinWidthPx = 8.0;
const _gutterMinWidthFactor = 0.3;
const _gutterCenterMin = 0.2;
const _gutterCenterMax = 0.8;
const _sideMinWidthFraction = 0.3;
const _minXSideTokens = 6;
const _wideTokenFraction = 0.5;
const _bandGapFactor = 2.5;
const _bandGapMinPx = 32.0;
const _maxDepth = 16;
const _gridCellWidthFraction = 0.2;
const _gridMinColumns = 4;
const _gridMinRows = 4;
const _gridMinCellsPerRow = 4;
const _gridMinTokens = 12;
const _gridColGapFactor = 2.0;
const _gridRowGapFactor = 1.5;
const _denseMinColumns = 3;
const _denseMinRows = 4;
const _denseMinCellsPerRow = 3;
const _denseMinRegularity = 0.75;

/// Python's sorted(): stable.
List<T> _sorted<T>(Iterable<T> items, int Function(T a, T b) compare) {
  final indexed = items.toList().asMap().entries.toList()
    ..sort((a, b) {
      final c = compare(a.value, b.value);
      return c != 0 ? c : a.key.compareTo(b.key);
    });
  return [for (final e in indexed) e.value];
}

int _cmpNum(num a, num b) => a.compareTo(b);

/// statistics.median: the mean of the two middle values for even counts.
double _median(List<num> values) {
  final s = [...values]..sort();
  final n = s.length;
  return n.isOdd ? s[n ~/ 2].toDouble() : (s[n ~/ 2 - 1] + s[n ~/ 2]) / 2.0;
}

double _pstdev(List<double> values) {
  final mean = values.reduce((a, b) => a + b) / values.length;
  final v = values.map((x) => (x - mean) * (x - mean)).reduce((a, b) => a + b) / values.length;
  return sqrt(v);
}

double _medianHeight(List<LayoutBox> t) =>
    max(1.0, _median([for (final b in t) max(1, b.y1 - b.y0)]));

double _contentWidth(List<LayoutBox> t) =>
    (t.map((b) => b.x1).reduce(max) - t.map((b) => b.x0).reduce(min)).toDouble();

(double, double)? _findGutter(List<LayoutBox> t, double medH) {
  final lo = t.map((b) => b.x0).reduce(min);
  final hi = t.map((b) => b.x1).reduce(max);
  final cw = hi - lo;
  if (cw <= 0) return null;
  final hist = List<int>.filled(cw + 2, 0);
  for (final b in t) {
    final a = b.x0 - lo, e = b.x1 - lo;
    final start = max(0, a);
    final end = min(hist.length, start + max(1, e - a));
    for (var i = start; i < end; i++) {
      hist[i]++;
    }
  }
  final limit = max(1, (_coverageLimit * t.length).floor());
  final minW = max(_gutterMinWidthPx, _gutterMinWidthFactor * medH);
  (double, double)? best;
  var bestW = 0.0;
  int? run;
  for (var i = 0; i <= hist.length; i++) {
    final empty = i < hist.length && hist[i] <= limit;
    if (empty) {
      run ??= i;
      continue;
    }
    if (run == null) continue;
    final w = (i - run).toDouble();
    final x0 = (run + lo).toDouble(), x1 = (i + lo).toDouble();
    run = null;
    if (w < minW) continue;
    final center = (x0 + x1) / 2.0;
    if (!(lo + _gutterCenterMin * cw < center && center < lo + _gutterCenterMax * cw)) {
      continue;
    }
    if (w > bestW) {
      best = (x0, x1);
      bestW = w;
    }
  }
  return best;
}

bool _raggedRight(List<LayoutBox> t) {
  if (t.length < 2) return true;
  final sd0 = _pstdev([for (final b in t) b.x0.toDouble()]);
  final sd1 = _pstdev([for (final b in t) b.x1.toDouble()]);
  return sd1 >= 0.5 * sd0;
}

final _digit = RegExp(r'\p{Nd}', unicode: true);
final _space = RegExp(r'\s');

double _digitRatio(String text) {
  final chars = text.split('').where((c) => !_space.hasMatch(c)).toList();
  if (chars.isEmpty) return 0;
  return chars.where(_digit.hasMatch).length / chars.length;
}

bool _mostlyNumeric(List<LayoutBox> t) {
  if (t.isEmpty) return false;
  return t.where((b) => _digitRatio(b.text) >= 0.4).length / t.length >= 0.5;
}

bool _fillsColumn(List<LayoutBox> t) {
  if (t.isEmpty) return false;
  final sideW = t.map((b) => b.x1).reduce(max) - t.map((b) => b.x0).reduce(min);
  if (sideW <= 0) return false;
  return _median([for (final b in t) b.x1 - b.x0]) >= 0.4 * sideW;
}

List<List<LayoutBox>> _gridColumns(List<LayoutBox> t, double medH) {
  final cols = <(double, List<LayoutBox>)>[];
  for (final b in _sorted(t, (a, c) => _cmpNum(a.cx, c.cx))) {
    if (cols.isNotEmpty && b.cx - cols.last.$1 <= _gridColGapFactor * medH) {
      cols.last.$2.add(b);
    } else {
      cols.add((b.cx, [b]));
    }
  }
  return [for (final c in cols) c.$2];
}

List<List<LayoutBox>> _gridRows(List<LayoutBox> t, double medH) {
  final rows = <List<LayoutBox>>[];
  var cur = <LayoutBox>[];
  int? curY1;
  for (final b in _sorted(t, (a, c) => _cmpNum(a.y0, c.y0))) {
    if (cur.isNotEmpty && b.y0 - curY1! > _gridRowGapFactor * medH) {
      rows.add(cur);
      cur = [];
      curY1 = null;
    }
    cur.add(b);
    curY1 = curY1 == null ? b.y1 : max(curY1, b.y1);
  }
  if (cur.isNotEmpty) rows.add(cur);
  return rows;
}

Map<LayoutBox, int> _columnOf(List<List<LayoutBox>> cols) => {
  for (var i = 0; i < cols.length; i++)
    for (final b in cols[i]) b: i,
};

bool _gridLike(List<LayoutBox> t, double medH) {
  if (t.length < _gridMinTokens) return false;
  final cw = _contentWidth(t);
  if (cw <= 0) return false;
  if (_median([for (final b in t) b.x1 - b.x0]) > _gridCellWidthFraction * cw) return false;
  final cols = _gridColumns(t, medH);
  if (cols.length < _gridMinColumns) return false;
  final rows = _gridRows(t, medH);
  if (rows.length < _gridMinRows) return false;
  final colOf = _columnOf(cols);
  return _median([for (final r in rows) {for (final b in r) colOf[b]}.length]) >=
      _gridMinCellsPerRow;
}

List<LayoutBox> _tableCellOrder(List<LayoutBox> t, double medH) {
  if (t.length < 2) return [...t];
  final cols = _gridColumns(t, medH);
  final colOf = _columnOf(cols);
  return [
    for (final row in _gridRows(t, medH))
      for (var i = 0; i < cols.length; i++)
        ..._sorted(row.where((b) => colOf[b] == i), (a, c) {
          final y = _cmpNum(a.y0, c.y0);
          return y != 0 ? y : _cmpNum(a.x0, c.x0);
        }),
  ];
}

List<List<LayoutBox>> _yRows(List<LayoutBox> t, double medH) {
  final rows = <(List<int>, List<LayoutBox>)>[]; // ([y0, y1], boxes)
  for (final b in _sorted(t, (a, c) => _cmpNum(a.cy, c.cy))) {
    var placed = false;
    for (final row in rows) {
      final rcy = (row.$1[0] + row.$1[1]) / 2.0;
      if ((b.cy - rcy).abs() <= 0.5 * medH) {
        row.$2.add(b);
        row.$1[0] = min(row.$1[0], b.y0);
        row.$1[1] = max(row.$1[1], b.y1);
        placed = true;
        break;
      }
    }
    if (!placed) rows.add(([b.y0, b.y1], [b]));
  }
  return [for (final r in rows) r.$2];
}

bool _denseGridLike(List<LayoutBox> t, double medH) {
  if (t.length < _gridMinTokens) return false;
  final cw = _contentWidth(t);
  if (cw <= 0) return false;
  if (_median([for (final b in t) b.x1 - b.x0]) > _gridCellWidthFraction * cw) return false;
  final cols = _gridColumns(t, medH);
  if (cols.length < _denseMinColumns) return false;
  final rows = _yRows(t, medH);
  if (rows.length < _denseMinRows) return false;
  final colOf = _columnOf(cols);
  final perRow = [for (final r in rows) {for (final b in r) colOf[b]}.length];
  if (_median(perRow) < _denseMinCellsPerRow) return false;
  return perRow.where((n) => n >= _denseMinCellsPerRow).length / perRow.length >=
      _denseMinRegularity;
}

List<LayoutBox> _denseTableOrder(List<LayoutBox> t, double medH) {
  if (t.length < 2) return [...t];
  return [
    for (final row in _yRows(t, medH))
      ..._sorted(row, (a, c) {
        final x = _cmpNum(a.x0, c.x0);
        return x != 0 ? x : _cmpNum(a.y0, c.y0);
      }),
  ];
}

double _yOverlap(LayoutBox a, LayoutBox b) => (min(a.y1, b.y1) - max(a.y0, b.y0)).toDouble();

Set<LayoutBox> _standaloneWide(List<LayoutBox> t, double cw) {
  if (cw <= 0) return {};
  return {
    for (final b in t)
      if (b.x1 - b.x0 >= _wideTokenFraction * cw &&
          !t.any((o) => !identical(o, b) && _yOverlap(b, o) > 1.0))
        b,
  };
}

List<List<LayoutBox>> _bands(List<LayoutBox> t, double medH, Set<LayoutBox> wide) {
  final items = _sorted(t, (a, c) {
    final y = _cmpNum(a.y0, c.y0);
    return y != 0 ? y : _cmpNum(a.y1, c.y1);
  });
  final gap = max(_bandGapFactor * medH, _bandGapMinPx);
  final bands = <List<LayoutBox>>[];
  var cur = <LayoutBox>[];
  var curY1 = 0;
  for (final b in items) {
    if (wide.contains(b)) {
      if (cur.isNotEmpty) {
        bands.add(cur);
        cur = [];
      }
      bands.add([b]);
      continue;
    }
    if (cur.isEmpty) {
      cur = [b];
      curY1 = b.y1;
    } else if (b.y0 - curY1 <= gap) {
      cur.add(b);
      curY1 = max(curY1, b.y1);
    } else {
      bands.add(cur);
      cur = [b];
      curY1 = b.y1;
    }
  }
  if (cur.isNotEmpty) bands.add(cur);
  return bands;
}

class _Stats {
  int splits = 0, tables = 0, dense = 0;
  bool get changed => splits + tables + dense > 0;
}

List<LayoutBox>? _columnSplit(List<LayoutBox> t, double medH, int minSide, _Stats stats) {
  final gutter = _findGutter(t, medH);
  if (gutter == null) return null;
  final mid = (gutter.$1 + gutter.$2) / 2.0;
  final left = [for (final b in t) if (b.cx < mid) b];
  final right = [for (final b in t) if (b.cx >= mid) b];
  if (left.length < minSide || right.length < minSide) return null;
  if (!_raggedRight(right) || _mostlyNumeric(right)) return null;
  if (!_fillsColumn(left) || !_fillsColumn(right)) return null;
  final cw = _contentWidth(t);
  if (_contentWidth(left) < _sideMinWidthFraction * cw ||
      _contentWidth(right) < _sideMinWidthFraction * cw) {
    return null;
  }
  stats.splits++;
  // As in the desktop code, both sides recurse at depth 1.
  return [..._sortRegion(left, minSide, 1, stats), ..._sortRegion(right, minSide, 1, stats)];
}

List<LayoutBox> _sortRegion(List<LayoutBox> t, int minSide, int depth, _Stats stats) {
  if (t.length <= 1 || depth >= _maxDepth) return [...t];
  final medH = _medianHeight(t);
  final split = _columnSplit(t, medH, minSide, stats);
  if (split != null) return split;
  final cw = _contentWidth(t);
  var wide = _standaloneWide(t, cw);
  if (wide.length >= 0.5 * t.length) wide = {};
  final bands = _bands(t, medH, wide);
  if (bands.length <= 1) {
    if (_gridLike(t, medH)) {
      stats.tables++;
      return _tableCellOrder(t, medH);
    }
    if (_denseGridLike(t, medH)) {
      stats.dense++;
      return _denseTableOrder(t, medH);
    }
    return [...t];
  }
  return [for (final band in bands) ..._sortRegion(band, minSide, depth + 1, stats)];
}

/// Indices of [boxes] in reading order. Unchanged order (0, 1, 2, ...) when
/// no column split or table was found anywhere.
List<int> readingOrder(List<LayoutBox> boxes) {
  if (boxes.isEmpty) return const [];
  final stats = _Stats();
  final out = _sortRegion(boxes, _minXSideTokens, 0, stats);
  if (!stats.changed) return [for (var i = 0; i < boxes.length; i++) i];
  final index = {for (var i = 0; i < boxes.length; i++) boxes[i]: i};
  return [for (final b in out) index[b]!];
}

/// Recognised lines (bbox = [left, top, width, height]) in reading order.
List<Map<String, dynamic>> sortLines(List<Map<String, dynamic>> lines) {
  final boxes = [
    for (final line in lines)
      () {
        final b = (line['bbox'] as List).map((v) => (v as num).toDouble()).toList();
        return LayoutBox(
          line['text'] as String? ?? '',
          b[0].round(),
          b[1].round(),
          (b[0] + b[2]).round(),
          (b[1] + b[3]).round(),
        );
      }(),
  ];
  return [for (final i in readingOrder(boxes)) lines[i]];
}
