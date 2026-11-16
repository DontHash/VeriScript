import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/documents.dart';

/// docs/TECH_UPGRADE_PLAN.md C3: the native blur/glare measures against the
/// Python reference. Photos are pushed by hand (local data, not shipped) to
/// the app's files/quality/ (adb push, then `run-as` cp); the printed JSON goes to
/// `python -m evals.harness.eval_capture_quality --parity <file>`.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('capture quality parity', (tester) async {
    final dir = Directory('${(await getApplicationSupportDirectory()).path}/quality');
    final files = dir.existsSync()
        ? (dir.listSync().whereType<File>().toList()..sort((a, b) => a.path.compareTo(b.path)))
        : <File>[];
    final out = <String, Map<String, Object?>>{};
    for (final f in files) {
      final clock = Stopwatch()..start();
      final q = await readCaptureQuality(f.path);
      final cut = await native.invokeMapMethod<String, dynamic>('cutOff', {'path': f.path});
      final hash = await readPageFingerprint(f.path);
      out[f.uri.pathSegments.last] = {
        'sharpness': q.sharpness, 'lapvar': q.lapVar, 'glare': q.glare,
        'seconds': clock.elapsedMilliseconds / 1000,
        'cut': cut, 'hash': hash,
      };
    }
    // ignore: avoid_print
    print('QUALITY_PARITY ${jsonEncode(out)}');
    expect(out, isNotEmpty);
  }, timeout: const Timeout(Duration(minutes: 10)));
}
