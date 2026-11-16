import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/capture.dart';
import 'package:veriscript_mobile/capture_quality.dart';

/// docs/TECH_UPGRADE_PLAN.md C3: blur and glare warnings are advisory.
void main() {
  CaptureQuality q({double sharpness = .6, double lapVar = 900, double glare = 0}) =>
      CaptureQuality(sharpness: sharpness, lapVar: lapVar, glare: glare);

  test('thresholds match the evaluated reference', () {
    expect(q().ok, isTrue);
    expect(q(sharpness: .39).blurry, isTrue);
    expect(q(lapVar: 249).blurry, isTrue);
    expect(q(glare: .03).hasGlare, isTrue);
    expect(q(glare: .029).hasGlare, isFalse);
    expect(q(sharpness: .2, glare: .1).problem, contains('blurry and has a bright glare'));
    final parsed = CaptureQuality.fromMap({'sharpness': .3, 'lapvar': 100, 'glare': .05});
    expect([parsed.blurry, parsed.hasGlare], [true, true]);
  });

  Future<bool?> ask(WidgetTester tester, CaptureQuality? quality, String? tap) async {
    bool? kept;
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => TextButton(
          onPressed: () async => kept = await keepAfterQualityCheck(context, quality),
          child: const Text('capture'),
        ),
      ),
    ));
    await tester.tap(find.text('capture'));
    await tester.pumpAndSettle();
    if (tap != null) {
      expect(find.text('Retake this page?'), findsOneWidget);
      if (tap == 'back') {
        await tester.tapAt(const Offset(5, 5)); // close the prompt without choosing
      } else {
        await tester.tap(find.text(tap));
      }
      await tester.pumpAndSettle();
    } else {
      expect(find.text('Retake this page?'), findsNothing);
    }
    return kept;
  }

  testWidgets('a good or unchecked photo is kept without asking', (tester) async {
    expect(await ask(tester, q(), null), isTrue);
    expect(await ask(tester, null, null), isTrue);
  });

  testWidgets('a blurry photo offers a retake', (tester) async {
    expect(await ask(tester, q(sharpness: .2), 'Retake'), isFalse);
    expect(find.textContaining('looks blurry'), findsNothing);
  });

  testWidgets('the user can keep a flagged photo, also by closing the prompt', (tester) async {
    expect(await ask(tester, q(glare: .1), 'Keep photo'), isTrue);
    expect(await ask(tester, q(glare: .1), 'back'), isTrue);
  });
}
