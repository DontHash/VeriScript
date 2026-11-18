import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/scan/scan_models.dart';

void main() {
  test('parses camera capabilities and keeps the selected back camera', () {
    final capabilities = ScanCameraCapabilities.fromMap({
      'probeVersion': 1,
      'device': 'Test Phone',
      'manufacturer': 'Example',
      'sdk': 35,
      'cameras': [
        {
          'id': '0',
          'facing': 'back',
          'hardwareLevel': 'FULL',
          'capabilities': ['BACKWARD_COMPATIBLE', 'MANUAL_SENSOR'],
          'manualSensor': true,
          'manualPostProcessing': true,
          'raw': false,
          'flash': true,
          'sensorOrientation': 90,
          'aeMin': -6,
          'aeMax': 6,
          'aeStep': 0.1667,
          'afModes': [0, 1, 3, 4],
          'awbModes': [0, 1, 2],
          'focalLengths': [4.25],
          'pixelArray': {'width': 4032, 'height': 3024},
          'jpegSizes': [
            {'width': 4032, 'height': 3024, 'megapixels': 12.19},
            {'width': 1920, 'height': 1080, 'megapixels': 2.07},
          ],
        },
        {'id': '1', 'facing': 'front', 'error': 'probe failed'},
      ],
      'selected': {
        'id': '0',
        'facing': 'back',
        'hardwareLevel': 'FULL',
        'capabilities': ['MANUAL_SENSOR'],
        'manualSensor': true,
        'jpegSizes': [
          {'width': 4032, 'height': 3024, 'megapixels': 12.19},
        ],
      },
    });

    expect(capabilities.cameras, hasLength(2));
    expect(capabilities.selected?.id, '0');
    expect(capabilities.selected?.isBack, isTrue);
    expect(capabilities.selected?.manualSensor, isTrue);
    expect(capabilities.selected?.jpegSizes.first.mp, 12.19);
    expect(capabilities.cameras.last.error, 'probe failed');
    expect(capabilities.toDiagnosticString(), contains('Test Phone'));
    expect(capabilities.toJsonString(), contains('4032'));
  });

  test('tolerates missing fields', () {
    final capabilities = ScanCameraCapabilities.fromMap({});
    expect(capabilities.cameras, isEmpty);
    expect(capabilities.selected, isNull);
    final camera = ScanCameraInfo.fromMap({});
    expect(camera.id, '?');
    expect(camera.aeStep, 0);
    expect(camera.jpegSizes, isEmpty);
  });
}
