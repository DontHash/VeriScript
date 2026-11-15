import 'dart:io';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'documents.dart';

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
      final resultLines = best!
          .map(
            (l) => <String, dynamic>{
              ...l,
              'original': l['text'],
              'reviewed': false,
            },
          )
          .toList();
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
        final repeat = (await _read(
          crop,
          reader,
        )).map((l) => l['text']).join('\n');
        line['digitAlternative'] = repeat;
        line['digitCheck'] = compareDigitReadings(line['original'], repeat);
        line['digitMethod'] = 'same-engine-enlarged-contrast-crop';
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

List<String> digitGroups(String text) => RegExp(r'[0-9०-९]+')
    .allMatches(text)
    .map(
      (m) => String.fromCharCodes(
        m
            .group(0)!
            .runes
            .map((c) => c >= 0x966 && c <= 0x96f ? c - 0x966 + 48 : c),
      ),
    )
    .toList();

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

String reviewLabel(Map<String, dynamic> line) {
  if (line['reviewed'] == true) return 'Confirmed by you';
  return switch (line['digitCheck']) {
    'conflict' => 'Digit disagreement · tap to compare',
    'unreadable' => 'Digit re-read unclear · check the image',
    'matched' => 'Digit re-read agrees · confirm against the image',
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
      RegExp(r'[0-9०-९�]').hasMatch(line['text'] as String);
}
