import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/capture.dart';
import 'package:veriscript_mobile/capture_quality.dart';

/// docs/TECH_UPGRADE_PLAN.md C4: the same page shot twice keeps the sharper
/// photo when the user agrees; otherwise both are kept.
void main() {
  test('fingerprint distance counts differing bits', () {
    final zero = '0' * 64;
    expect(fingerprintDistance(zero, zero), 0);
    expect(fingerprintDistance(zero, 'f${'0' * 63}'), 4);
    expect(fingerprintDistance(zero, 'f' * 64), 256);
    expect(fingerprintDistance(zero, 'short'), 256);
    // Threshold from the evaluation: 88 of 256 bits.
    expect(samePage(zero, '${'f' * 22}${'0' * 42}'), isTrue);
    expect(samePage(zero, '${'f' * 22}1${'0' * 41}'), isFalse);
    expect(samePage(null, zero), isFalse);
  });

  Future<SamePageChoice?> ask(
    WidgetTester tester,
    bool newIsSharper,
    String? tap,
  ) async {
    SamePageChoice? choice;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () async =>
                choice = await askSamePage(context, newIsSharper: newIsSharper),
            child: const Text('capture'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('capture'));
    await tester.pumpAndSettle();
    expect(find.text('Same page again?'), findsOneWidget);
    if (tap == null) {
      await tester.tapAt(const Offset(5, 5));
    } else {
      await tester.tap(find.text(tap));
    }
    await tester.pumpAndSettle();
    return choice;
  }

  testWidgets('says which photo is sharper and keeps it', (tester) async {
    expect(
      await ask(tester, true, 'Keep the sharper one'),
      SamePageChoice.keepSharper,
    );
    expect(
      await ask(tester, false, 'Keep the sharper one'),
      SamePageChoice.keepSharper,
    );
  });

  testWidgets('keeps both when asked or when the prompt is closed', (
    tester,
  ) async {
    expect(await ask(tester, true, 'Keep both'), SamePageChoice.keepBoth);
    expect(await ask(tester, false, null), SamePageChoice.keepBoth);
  });
}
