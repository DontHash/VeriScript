import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/main.dart';

class _EmptyStore extends DocumentStore {
  _EmptyStore() : super(Directory.systemTemp);
  @override
  Future<List<ScanDocument>> list() async => [];
}

void main() {
  testWidgets('first launch explains privacy and the camera, once', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final handle = tester.ensureSemantics();
    SharedPreferences.setMockInitialValues({});
    final settings = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      VeriScriptApp(settings: settings, store: _EmptyStore()),
    );
    await tester.pumpAndSettle();

    expect(find.text('Welcome to VeriScript'), findsOneWidget);
    expect(find.text('Everything stays on your phone'), findsOneWidget);
    expect(find.text('The camera is only for your pages'), findsOneWidget);
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    await expectLater(tester, meetsGuideline(textContrastGuideline));

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();
    expect(find.text('Scan pages'), findsOneWidget);
    expect(settings.getBool('welcomed'), isTrue);

    // A second launch goes straight to the library.
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(
      VeriScriptApp(settings: settings, store: _EmptyStore()),
    );
    await tester.pumpAndSettle();
    expect(find.text('Welcome to VeriScript'), findsNothing);
    handle.dispose();
  });
}
