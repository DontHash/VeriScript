import 'dart:io';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'documents.dart';

class OfflineProcessor {
  OfflineProcessor(this.language);
  final String language;
  bool cancelled = false;
  TextRecognizer get recognizer => TextRecognizer(
    script: language == 'en'
        ? TextRecognitionScript.latin
        : TextRecognitionScript.devanagiri,
  );

  Future<void> recognize(
    ScanPage page, {
    bool autoRotate = true,
    bool checkDigits = true,
    void Function(String stage)? onProgress,
  }) async {
    final reader = recognizer;
    final paths = <String>[];
    try {
      RecognizedText? best;
      double bestScore = -1;
      String bestPath = page.path;
      for (final degrees in autoRotate ? [0, 90, 180, 270] : [0]) {
        if (cancelled) throw StateError('Operation cancelled');
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
        final result = await reader.processImage(InputImage.fromFilePath(path));
        final lines = result.blocks.expand((b) => b.lines);
        // ML Kit can read upside-down text. Its reported line angle distinguishes
        // that from truly upright text; rectangle shape alone cannot do so.
        final score = lines.fold<double>(
          0,
          (sum, line) =>
              sum +
              line.text.runes.length *
                  orientationWeight(
                    line.angle,
                    line.boundingBox.width,
                    line.boundingBox.height,
                  ) *
                  (line.confidence ?? .75),
        );
        if (score > bestScore * 1.12 || best == null) {
          best = result;
          bestScore = score;
          bestPath = path;
        }
      }
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
      final resultLines = best!.blocks
          .expand((b) => b.lines)
          .map(
            (l) => <String, dynamic>{
              'text': l.text,
              'original': l.text,
              'confidence': l.confidence,
              'angle': l.angle,
              'bbox': [
                l.boundingBox.left,
                l.boundingBox.top,
                l.boundingBox.width,
                l.boundingBox.height,
              ],
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
        final repeat = await reader.processImage(InputImage.fromFilePath(crop));
        line['digitAlternative'] = repeat.text;
        line['digitCheck'] = compareDigitReadings(
          line['original'],
          repeat.text,
        );
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
      paths.remove(resultPath);
    } finally {
      await reader.close();
      for (final path in paths) {
        final file = File(path);
        if (await file.exists()) await file.delete();
      }
    }
  }
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
