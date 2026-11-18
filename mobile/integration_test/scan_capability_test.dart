import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:veriscript_mobile/scan/scan_camera_api.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('native camera capability probe responds', (tester) async {
    final capabilities = await const ScanCameraApi().getCapabilities();
    expect(capabilities.device, isNotEmpty);
    expect(capabilities.sdk, greaterThan(0));
    // Printed so a device run records the actual JPEG sizes/hardware level.
    // ignore: avoid_print
    print(capabilities.toDiagnosticString());
  });
}
