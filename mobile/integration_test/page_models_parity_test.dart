import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/documents.dart';

/// docs/TECH_UPGRADE_PLAN.md F1 + F3 on the phone, against the Python
/// reference. Pushed by hand to files/models/ (adb push, then run-as cp):
/// `*_finger.png` go through `cleanFingers`, `*_curved.png` through
/// `flatten`; outputs land in files/models/out/ for the host to compare.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('flatten and finger cleanup', (tester) async {
    final dir = Directory('${(await getApplicationSupportDirectory()).path}/models');
    final out = Directory('${dir.path}/out')..createSync(recursive: true);
    final files = dir.listSync().whereType<File>().where((f) => f.path.endsWith('.png')).toList()
      ..sort((a, b) => a.path.compareTo(b.path));
    final report = <String, Object?>{};
    for (final f in files) {
      final name = f.uri.pathSegments.last;
      final method = name.contains('_finger') ? 'cleanFingers' : 'flatten';
      final clock = Stopwatch()..start();
      final result = await native.invokeMapMethod<String, dynamic>(method, {
        'path': f.path,
        'out': '${out.path}/${name.replaceAll('.png', '.png')}',
      });
      report[name] = {...?result, 'seconds': clock.elapsedMilliseconds / 1000};
    }
    // ignore: avoid_print
    print('MODELS ${jsonEncode(report)}');
    expect(report, isNotEmpty);
  }, timeout: const Timeout(Duration(minutes: 10)));
}
