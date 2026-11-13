import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/scan/scan_camera_api.dart';
import 'package:veriscript_mobile/scan/scan_diagnostics_screen.dart';
import 'package:veriscript_mobile/scan/scan_models.dart';

class _FakeApi extends ScanCameraApi {
  const _FakeApi();

  @override
  Future<ScanCameraCapabilities> getCapabilities() async =>
      ScanCameraCapabilities.fromMap({
        'probeVersion': 1,
        'device': 'Test Phone',
        'manufacturer': 'Example',
        'sdk': 35,
        'cameras': [
          {
            'id': '0',
            'facing': 'back',
            'hardwareLevel': 'FULL',
            'capabilities': ['MANUAL_SENSOR'],
            'manualSensor': true,
            'manualPostProcessing': true,
            'raw': false,
            'flash': true,
            'sensorOrientation': 90,
            'aeMin': -2,
            'aeMax': 2,
            'aeMinIndex': -6,
            'aeMaxIndex': 6,
            'aeStep': 0.333,
            'afModes': [0, 1],
            'awbModes': [0, 1],
            'focalLengths': [4.2],
            'pixelArray': {'width': 4032, 'height': 3024},
            'jpegSizes': [
              {'width': 4032, 'height': 3024, 'megapixels': 12.19},
            ],
          },
        ],
        'selected': {
          'id': '0',
          'facing': 'back',
          'hardwareLevel': 'FULL',
          'manualSensor': true,
          'jpegSizes': [
            {'width': 4032, 'height': 3024, 'megapixels': 12.19},
          ],
        },
      });
}

void main() {
  testWidgets('diagnostics screen shows the selected camera', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: ScanDiagnosticsScreen(api: _FakeApi())),
    );
    await tester.pumpAndSettle();

    expect(find.text('Camera diagnostics'), findsOneWidget);
    expect(find.textContaining('Test Phone'), findsOneWidget);
    expect(find.textContaining('Selected back camera'), findsOneWidget);
    expect(find.textContaining('4032 x 3024'), findsWidgets);
    await tester.scrollUntilVisible(
      find.text('Copy readable report'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Copy readable report'), findsOneWidget);
  });
}
