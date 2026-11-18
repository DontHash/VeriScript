import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/review.dart';

/// docs/TECH_UPGRADE_PLAN.md E5: the password is asked for twice and
/// checked before any export starts.
void main() {
  Future<String?> run(WidgetTester tester, List<(String, String)> tries, {bool cancel = false}) async {
    String? result = 'not closed';
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => TextButton(
          onPressed: () async => result = await askPdfPassword(context),
          child: const Text('export'),
        ),
      ),
    ));
    await tester.tap(find.text('export'));
    await tester.pumpAndSettle();
    for (final (a, b) in tries) {
      await tester.enterText(find.widgetWithText(TextField, 'Password'), a);
      await tester.enterText(find.widgetWithText(TextField, 'Password again'), b);
      await tester.tap(find.text('Protect PDF'));
      await tester.pumpAndSettle();
    }
    if (cancel) {
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
    }
    return result;
  }

  testWidgets('short or different passwords are refused with a reason', (tester) async {
    expect(await run(tester, [('short', 'short')]), 'not closed');
    expect(find.text('Use at least 6 characters.'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Password'), 'ward-7 रकम');
    await tester.enterText(find.widgetWithText(TextField, 'Password again'), 'ward-7 रक');
    await tester.tap(find.text('Protect PDF'));
    await tester.pumpAndSettle();
    expect(find.text('The two passwords differ.'), findsOneWidget);
  });

  testWidgets('a matching password is returned; cancel returns nothing', (tester) async {
    expect(await run(tester, [('ward-7 रकम', 'ward-7 रकम')]), 'ward-7 रकम');
    expect(await run(tester, const [], cancel: true), isNull);
  });
}
