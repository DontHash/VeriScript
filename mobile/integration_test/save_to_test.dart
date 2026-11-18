import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/exports.dart';

/// docs/TECH_UPGRADE_PLAN.md E5: "Save to…" through Android's own picker.
/// Needs someone (or `adb shell input`) to press Save in the picker; the
/// host then checks the copy in Downloads byte for byte.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('save an export through the system picker', (tester) async {
    final dir = await getTemporaryDirectory();
    final file = File('${dir.path}/VeriScript save check.pdf');
    final bytes = List<int>.generate(20 * 1024 * 1024, (i) => (i * 31) & 0xff);
    await file.writeAsBytes(bytes, flush: true);
    final saved = await saveExportAs(file.path);
    // ignore: avoid_print
    print('SAVE_RESULT saved=$saved bytes=${bytes.length}');
    expect(saved, isTrue);
  }, timeout: const Timeout(Duration(minutes: 5)));
}
