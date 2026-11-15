import 'dart:io';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'documents.dart';
import 'layout.dart';

class OfflineProcessor {
  OfflineProcessor(this.language, {this.engine = 'mlkit'});
  final String language;
  final String engine;
  bool cancelled = false;

  /// Clockwise degrees the last recognize() turned the page (0 = as given).
  int lastRotation = 0;

  /// Rotations the last recognize() read, in order (its length is the
  /// number of full-page reads orientation needed).
  List<int> lastTried = const [];
  int get lastReads => lastTried.length;

  /// How number lines are re-checked (docs/TECH_UPGRADE_PLAN.md D2):
  /// 'same' - the same engine reads an enlarged, contrast-adjusted crop;
  /// 'cross' - the other bundled engine reads that crop (independent);
  /// 'both' - record both, decide with 'same' (for measurement only).
  /// Default 'cross' for both readers (measured 2026-11-16 on 16 pages):
  /// ML Kit reading: wrong number lines caught 2/4 vs 1/4, false alarms 6% vs
  /// 10%, 68 vs 84 ms per line; RapidOCR reading: caught 2/3 vs 0/3, false
  /// alarms 12% vs 32%, 0.1 s vs 4.8 s per line.
  String digitMode = 'cross';

  /// The other engine's reading of a digit crop (recognition only).
  Future<String> _crossRead(String crop, TextRecognizer? mlkit) async {
    if (engine == 'mlkit') {
      final result = await native.invokeMapMethod<String, dynamic>(
        'rapidOcrLine',
        {'path': crop, 'language': language},
      );
      return (result?['text'] as String?) ?? '';
    }
    final result = await mlkit!.processImage(InputImage.fromFilePath(crop));
    return result.blocks.expand((b) => b.lines).map((l) => l.text).join('\n');
  }

  /// The chosen read's text in the engine's own line order, before
  /// [sortLines] (for measuring the reading-order step).
  String lastEngineOrderText = '';

  TextRecognizer get recognizer => TextRecognizer(
    script: language == 'en'
        ? TextRecognitionScript.latin
        : TextRecognitionScript.devanagiri,
  );

  Future<List<Map<String, dynamic>>> _read(
    String path,
    TextRecognizer? reader,
  ) async {
    if (engine == 'rapidocr') {
      final result = await native.invokeListMethod<dynamic>('rapidOcr', {
        'path': path,
        'language': language,
      });
      return result!
          .map((row) => Map<String, dynamic>.from(row as Map))
          .toList();
    }
    final result = await reader!.processImage(InputImage.fromFilePath(path));
    return result.blocks
        .expand((block) => block.lines)
        .map(
          (line) => <String, dynamic>{
            'text': line.text,
            'confidence': line.confidence,
            'angle': line.angle,
            'bbox': [
              line.boundingBox.left,
              line.boundingBox.top,
              line.boundingBox.width,
              line.boundingBox.height,
            ],
            'backend': 'mlkit',
          },
        )
        .toList();
  }

  Future<void> recognize(
    ScanPage page, {
    bool autoRotate = true,
    bool checkDigits = true,
    void Function(String stage)? onProgress,
  }) async {
    if (engine != 'mlkit' && engine != 'rapidocr') {
      throw ArgumentError('Unknown OCR engine: $engine');
    }
    final reader = engine == 'mlkit' ? recognizer : null;
    final crossReader = engine == 'rapidocr' && digitMode != 'same' && checkDigits
        ? recognizer
        : null;
    final paths = <String>[];
    try {
      List<Map<String, dynamic>>? best;
      double bestScore = -1;
      String bestPath = page.path;
      var bestDegrees = 0;
      final tried = <int>[];
      Future<List<Map<String, dynamic>>> attempt(int degrees) async {
        if (cancelled) throw StateError('Operation cancelled');
        tried.add(degrees);
        onProgress?.call(
          degrees == 0 ? 'Reading text' : 'Checking orientation · $degrees°',
        );
        var path = page.path;
        if (degrees != 0) {
          path = '${page.path}.$degrees.jpg';
          paths.add(path);
          await native.invokeMethod('rotate', {
            'path': page.path,
            'out': path,
            'degrees': degrees,
          });
        }
        final result = await _read(path, reader);
        final lines = result;
        // ML Kit can read upside-down text. Its reported line angle distinguishes
        // that from truly upright text; rectangle shape alone cannot do so.
        final score = lines.fold<double>(
          0,
          (sum, line) =>
              sum +
              (line['text'] as String).runes.length *
                  orientationWeight(
                    (line['angle'] as num?)?.toDouble(),
                    (line['bbox'][2] as num).toDouble(),
                    (line['bbox'][3] as num).toDouble(),
                  ) *
                  ((line['confidence'] as num?)?.toDouble() ?? .75),
        );
        if (score > bestScore * 1.12 || best == null) {
          best = result;
          bestScore = score;
          bestPath = path;
          bestDegrees = degrees;
        }
        return result;
      }

      // Orientation (docs/TECH_UPGRADE_PLAN.md D1): read the page as given;
      // most pages are upright, so one read is enough. Otherwise the line
      // angles of that read say which way the page is turned: try that
      // rotation first and stop at the first read that looks upright. All
      // four rotations are read only when none does, and the best-scoring
      // read wins as before.
      //
      // The early stop needs line angles that tell up from down: ML Kit
      // reports them, and the native port's 0/180 line classifier runs for
      // English only. For RapidOCR on Devanagari an upside-down page still
      // looks "upright", so it compares all four rotations as before
      // (measured 2026-11-15: early stop got 2 of 5 turned pages wrong).
      final directional = engine == 'mlkit' || language == 'en';
      final first = await attempt(0);
      if (autoRotate && !directional) {
        for (final degrees in [90, 180, 270]) {
          await attempt(degrees);
        }
      } else if (autoRotate && !looksUpright(first)) {
        for (final degrees in rotationOrder(first)) {
          if (looksUpright(await attempt(degrees))) break;
        }
      }
      lastTried = List.unmodifiable(tried);
      if (cancelled) throw StateError('Operation cancelled');
      var resultPath = page.path;
      var resultWidth = page.width, resultHeight = page.height;
      if (bestPath != page.path) {
        final target =
            '${page.path}.upright_${DateTime.now().microsecondsSinceEpoch}.jpg';
        await File(bestPath).copy(target);
        paths.add(target);
        resultPath = target;
        final info = await native.invokeMapMethod<String, dynamic>(
          'dimensions',
          {'path': target},
        );
        resultWidth = info!['width'];
        resultHeight = info['height'];
      }
      // Reading order (docs/TECH_UPGRADE_PLAN.md D4): two-column pages and
      // tables come back from the engines row by row; the desktop's measured
      // algorithm puts them in reading order and leaves everything else as is.
      lastEngineOrderText = best!.map((l) => l['text'] as String).join('\n');
      final resultLines = sortLines(best!)
          .map(
            (l) => <String, dynamic>{
              ...l,
              'original': l['text'],
              'reviewed': false,
            },
          )
          .toList();
      for (final line in resultLines) {
        final issue = digitScriptIssue(line['text'] as String);
        if (issue != null) line['digitScript'] = issue;
      }
      var checked = 0;
      for (final line in resultLines) {
        if (digitGroups(line['text']).isEmpty) continue;
        line['digitCheck'] = 'notChecked';
        if (!checkDigits || checked >= 80) continue;
        if (cancelled) throw StateError('Operation cancelled');
        checked++;
        onProgress?.call('Checking digits · line $checked');
        final crop = '$resultPath.digits_$checked.jpg';
        paths.add(crop);
        await native.invokeMethod('digitCrop', {
          'path': resultPath,
          'out': crop,
          'bbox': line['bbox'],
        });
        final clock = Stopwatch()..start();
        if (digitMode != 'cross') {
          final repeat = (await _read(
            crop,
            reader,
          )).map((l) => l['text']).join('\n');
          line['digitAlternative'] = repeat;
          line['digitCheck'] = compareDigitReadings(line['original'], repeat);
          line['digitMethod'] = 'same-engine-enlarged-contrast-crop';
        }
        final sameMs = clock.elapsedMilliseconds;
        if (digitMode != 'same') {
          final cross = await _crossRead(crop, crossReader);
          final verdict = compareDigitReadings(line['original'], cross);
          if (digitMode == 'cross') {
            line['digitAlternative'] = cross;
            line['digitCheck'] = verdict;
            line['digitMethod'] = 'other-engine-enlarged-contrast-crop';
          } else {
            line['digitCrossAlternative'] = cross;
            line['digitCrossCheck'] = verdict;
            line['digitSameMs'] = sameMs;
            line['digitCrossMs'] = clock.elapsedMilliseconds - sameMs;
          }
        }
      }
      if (cancelled) throw StateError('Operation cancelled');
      // Commit a complete page only. A cancelled digit check must not overwrite
      // reviewed text or leave a new image with stale geometry.
      page.protectText();
      page.path = resultPath;
      page.width = resultWidth;
      page.height = resultHeight;
      page.lines = resultLines;
      page.recognized = true;
      lastRotation = bestDegrees;
      paths.remove(resultPath);
    } finally {
      await reader?.close();
      await crossReader?.close();
      for (final path in paths) {
        final file = File(path);
        if (await file.exists()) await file.delete();
      }
    }
  }
}

/// Rotations to try after a read that does not look upright, most likely
/// first. Line angles are rounded to the nearest quarter turn and weighted by
/// text length; the page is turned back by that much (clockwise degrees).
/// Lines without an angle but taller than wide only say "sideways".
List<int> rotationOrder(List<Map<String, dynamic>> lines) {
  final votes = <int, double>{90: 0, 180: 0, 270: 0};
  for (final line in lines) {
    final n = (line['text'] as String).runes.length.toDouble();
    final angle = (line['angle'] as num?)?.toDouble();
    if (angle != null) {
      final quarter = ((angle % 360) / 90).round() % 4 * 90;
      final turn = (360 - quarter) % 360;
      if (turn != 0) votes[turn] = votes[turn]! + n;
    } else {
      final box = line['bbox'] as List;
      if ((box[3] as num) > (box[2] as num) * 1.5) {
        votes[90] = votes[90]! + n / 2;
        votes[270] = votes[270]! + n / 2;
      }
    }
  }
  final order = [90, 180, 270]
    ..sort((a, b) {
      final byVotes = votes[b]!.compareTo(votes[a]!);
      return byVotes != 0 ? byVotes : a.compareTo(b);
    });
  // A sideways guess that is wrong is most often the opposite quarter turn.
  if (order.first != 180) {
    final opposite = (order.first + 180) % 360;
    order
      ..remove(opposite)
      ..insert(1, opposite);
  }
  return order;
}

/// Whether a read looks upright: enough text, and most of it on lines whose
/// angle (or shape, when no angle is reported) is upright.
bool looksUpright(List<Map<String, dynamic>> lines) {
  var chars = 0, upright = 0;
  for (final line in lines) {
    final n = (line['text'] as String).runes.length;
    chars += n;
    final box = line['bbox'] as List;
    if (orientationWeight(
          (line['angle'] as num?)?.toDouble(),
          (box[2] as num).toDouble(),
          (box[3] as num).toDouble(),
        ) ==
        1) {
      upright += n;
    }
  }
  return chars >= 8 && upright >= chars * .7;
}

double orientationWeight(double? angle, double width, double height) {
  if (angle == null) return width >= height ? 1 : .25;
  final deviation = ((angle + 180) % 360 - 180).abs();
  return deviation <= 30
      ? 1
      : deviation <= 60
      ? .5
      : .1;
}

/// Digit runs as ASCII values. Devanagari and Bengali digits count by value,
/// so a re-read compares numbers, not scripts; [digitScriptIssue] reports
/// the script separately.
List<String> digitGroups(String text) => RegExp(r'[0-9०-९০-৯]+')
    .allMatches(text)
    .map(
      (m) => String.fromCharCodes(
        m.group(0)!.runes.map(
          (c) => c >= 0x966 && c <= 0x96f
              ? c - 0x966 + 48
              : c >= 0x9e6 && c <= 0x9ef
              ? c - 0x9e6 + 48
              : c,
        ),
      ),
    )
    .toList();

const _deva = r'०-९', _bengali = r'০-৯', _ascii = r'0-9';
final _anyDigit = RegExp('[$_ascii$_deva$_bengali]');
final _numericChars = RegExp('^[$_ascii$_deva$_bengali/.,:-]+\$');

/// Why the digits on a line need a second look because of their script, or
/// null. Never changes the text: the person decides.
///
/// - `bengaliDigit`: ML Kit's Devanagari model also covers Bengali, whose
///   digits look like Devanagari ones (০ for ०); measured on 2026-11-15.
/// - `mixedDigits`: one number mixes Devanagari and ASCII digits.
/// - `letterInNumber`: o, O, l or I inside an otherwise numeric token
///   (२०८३/०७/o१).
String? digitScriptIssue(String text) {
  if (RegExp('[$_bengali]').hasMatch(text)) return 'bengaliDigit';
  for (final token in text.split(RegExp(r'\s+'))) {
    if (!_anyDigit.hasMatch(token)) continue;
    if (RegExp('[$_ascii]').hasMatch(token) &&
        RegExp('[$_deva]').hasMatch(token)) {
      return 'mixedDigits';
    }
    final stripped = token.replaceAll(RegExp(r'[oOlI]'), '');
    if (stripped != token && _numericChars.hasMatch(stripped)) {
      return 'letterInNumber';
    }
  }
  return null;
}

/// Agreement is supporting evidence, never permission to replace the first read.
String compareDigitReadings(String original, String alternative) {
  final first = digitGroups(original), second = digitGroups(alternative);
  if (second.isEmpty) return 'unreadable';
  if (first.length != second.length) return 'conflict';
  for (var i = 0; i < first.length; i++) {
    if (first[i] != second[i]) return 'conflict';
  }
  return 'matched';
}

/// Whether the digits were re-read by the other engine (independent check).
bool crossChecked(Map<String, dynamic> line) =>
    (line['digitMethod'] as String? ?? '').startsWith('other-engine');

String reviewLabel(Map<String, dynamic> line) {
  if (line['reviewed'] == true) return 'Confirmed by you';
  switch (line['digitScript']) {
    case 'bengaliDigit':
      return 'Look-alike digit from another script · check each digit';
    case 'mixedDigits':
      return 'Number mixes digit scripts · check each digit';
    case 'letterInNumber':
      return 'Letter inside a number · check each digit';
  }
  return switch (line['digitCheck']) {
    'conflict' => crossChecked(line)
        ? 'Second reader disagrees on digits · tap to compare'
        : 'Digit disagreement · tap to compare',
    'unreadable' => crossChecked(line)
        ? 'Second reader could not read the digits · check the image'
        : 'Digit re-read unclear · check the image',
    'matched' => crossChecked(line)
        ? 'Second reader agrees · confirm against the image'
        : 'Digit re-read agrees · confirm against the image',
    'notChecked' => 'Digits not re-checked · tap to review',
    _ =>
      needsReview(line)
          ? 'Needs review · tap to correct'
          : 'OCR reading · tap to review',
  };
}

bool needsReview(Map<String, dynamic> line) {
  if (line['reviewed'] == true) return false;
  final confidence = line['confidence'] as num?;
  return confidence == null ||
      confidence < .8 ||
      line['digitScript'] != null ||
      RegExp(r'[0-9०-९০-৯�]').hasMatch(line['text'] as String);
}
