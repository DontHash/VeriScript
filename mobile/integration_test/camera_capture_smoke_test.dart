import 'package:camera/camera.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:veriscript_mobile/documents.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('camera plugin max preset produces a usable JPEG', (
    tester,
  ) async {
    final cameras = await availableCameras();
    if (cameras.isEmpty) {
      // ignore: avoid_print
      print('No camera on this device; skipping capture smoke test.');
      return;
    }
    final selected = cameras.firstWhere(
      (camera) => camera.lensDirection == CameraLensDirection.back,
      orElse: () => cameras.first,
    );
    final controller = CameraController(
      selected,
      ResolutionPreset.max,
      enableAudio: false,
    );
    await controller.initialize();
    try {
      final photo = await controller.takePicture();
      final info = await readCaptureInfo(photo.path);
      expect(info.width, greaterThan(0));
      expect(info.height, greaterThan(0));
      expect(info.isUsable, isTrue);
      // ignore: avoid_print
      print('Camera capture: ${info.summary}');
    } finally {
      await controller.dispose();
    }
  });
}
