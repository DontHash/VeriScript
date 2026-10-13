import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:veriscript_mobile/main.dart';
import 'package:veriscript_mobile/documents.dart';

class EmptyStore extends DocumentStore {
  EmptyStore() : super(Directory.systemTemp);
  @override
  Future<List<ScanDocument>> list() async => [];
}

void main() {
  for (final dark in [false, true]) {
    testWidgets(
      '${dark ? 'Night Studio' : 'Paper & Ink'} fits a narrow phone',
      (tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        SharedPreferences.setMockInitialValues({'theme': dark ? 2 : 1});
        await tester.pumpWidget(
          VeriScriptApp(
            settings: await SharedPreferences.getInstance(),
            store: EmptyStore(),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('VeriScript'), findsOneWidget);
        expect(tester.takeException(), isNull);
        expect(
          Theme.of(tester.element(find.byType(Scaffold))).brightness,
          dark ? Brightness.dark : Brightness.light,
        );
        await tester.tap(find.text('Settings'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      },
    );
  }
}
