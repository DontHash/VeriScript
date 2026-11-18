import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:veriscript_mobile/documents.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('native capture metadata reads a real JPEG', (tester) async {
    final directory = await getTemporaryDirectory();
    final white = img.Image(width: 1600, height: 1200);
    img.fill(white, color: img.ColorRgb8(245, 245, 245));
    final whiteFile = File('${directory.path}/scan-white.jpg');
    await whiteFile.writeAsBytes(img.encodeJpg(white, quality: 90));

    final whiteInfo = await readCaptureInfo(whiteFile.path);
    expect(whiteInfo.width, 1600);
    expect(whiteInfo.height, 1200);
    expect(whiteInfo.meanLuma, greaterThan(200));
    expect(whiteInfo.isUsable, isTrue);

    final black = img.Image(width: 800, height: 600);
    img.fill(black, color: img.ColorRgb8(0, 0, 0));
    final blackFile = File('${directory.path}/scan-black.jpg');
    await blackFile.writeAsBytes(img.encodeJpg(black, quality: 90));

    final blackInfo = await readCaptureInfo(blackFile.path);
    expect(blackInfo.isProbablyBlack, isTrue);
    expect(blackInfo.isUsable, isFalse);

    await whiteFile.delete();
    await blackFile.delete();
  });
}
