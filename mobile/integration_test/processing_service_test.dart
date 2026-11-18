import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

/// docs/TECH_UPGRADE_PLAN.md A3: the progress service starts as a foreground
/// service, updates, and stops. While the test holds it, the host can check
/// `adb shell dumpsys activity services com.veriscript.veriscript_mobile`.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('veriscript/background');

  testWidgets('progress service starts, updates and stops', (tester) async {
    await channel.invokeMethod<void>('start', {
      'title': 'Service check',
      'text': 'Page 1 of 3',
      'permille': 0,
    });
    for (var i = 1; i <= 15; i++) {
      await Future<void>.delayed(const Duration(seconds: 1));
      await channel.invokeMethod<void>('update', {
        'title': 'Service check',
        'text': 'Page ${1 + i ~/ 5} of 3',
        'permille': i * 60,
      });
    }
    // ignore: avoid_print
    print('SERVICE-CHECK-STOPPING');
    await channel.invokeMethod<void>('stop', const <String, Object>{});
    await Future<void>.delayed(const Duration(seconds: 3));
  });
}
