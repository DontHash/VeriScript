import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:veriscript_mobile/main.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/selection.dart';

double contrast(Color a, Color b) {
  final first = a.computeLuminance(), second = b.computeLuminance();
  return (first > second
      ? (first + 0.05) / (second + 0.05)
      : (second + 0.05) / (first + 0.05));
}

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
        SharedPreferences.setMockInitialValues({
          'theme': dark ? 2 : 1,
          'welcomed': true,
        });
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
        final scanCard = tester.widget<Card>(
          find.ancestor(
            of: find.text('Scan pages'),
            matching: find.byType(Card),
          ),
        );
        expect(scanCard.color, dark ? const Color(0xfff2b544) : null);
        final heading = tester.widget<Text>(
          find.text('From paper\nto possibility.'),
        );
        expect(heading.style!.fontFamily, 'Instrument Serif');
        final theme = Theme.of(tester.element(find.byType(Scaffold)));
        expect(theme.textTheme.bodyMedium!.fontFamily, 'Mukta');
        // Selected controls must retain readable foregrounds in either palette.
        expect(
          contrast(theme.colorScheme.onPrimary, theme.colorScheme.primary),
          greaterThanOrEqualTo(4.5),
        );
        final tabs = theme.tabBarTheme;
        expect(
          contrast(tabs.labelColor!, theme.scaffoldBackgroundColor),
          greaterThanOrEqualTo(4.5),
        );
        final icons = theme.iconButtonTheme.style!;
        expect(
          contrast(
            icons.foregroundColor!.resolve({WidgetState.selected})!,
            icons.backgroundColor!.resolve({WidgetState.selected})!,
          ),
          greaterThanOrEqualTo(4.5),
        );
        expect(
          icons.backgroundColor!.resolve({
            WidgetState.selected,
            WidgetState.disabled,
          }),
          isNull,
        );
        await tester.tap(find.text('Files'));
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<FilterChip>(find.widgetWithText(FilterChip, 'All'))
              .selected,
          isTrue,
        );
        await tester.tap(find.widgetWithText(FilterChip, 'Unfiled'));
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<FilterChip>(find.widgetWithText(FilterChip, 'All'))
              .selected,
          isFalse,
        );
        expect(
          tester
              .widget<FilterChip>(find.widgetWithText(FilterChip, 'Unfiled'))
              .selected,
          isTrue,
        );
        await tester.tap(find.text('Settings'));
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<Text>(find.text('Make yourself at home.'))
              .style!
              .fontFamily,
          'Instrument Serif',
        );
        await tester.tap(find.byType(DropdownButtonFormField<String>));
        await tester.pumpAndSettle();
        await tester.tap(find.text('English · Latin').last);
        await tester.pumpAndSettle();
        final language = tester.widget<SelectionLabel>(
          find.widgetWithText(SelectionLabel, 'English · Latin'),
        );
        expect(language.selected, isTrue);
        expect(
          (await SharedPreferences.getInstance()).getString('language'),
          'en',
        );
        final desktopReader = find.widgetWithText(
          SwitchListTile,
          'Desktop reader (preview)',
        );
        await tester.ensureVisible(desktopReader);
        expect(tester.widget<SwitchListTile>(desktopReader).value, isFalse);
        await tester.tap(desktopReader);
        await tester.pumpAndSettle();
        expect(
          (await SharedPreferences.getInstance()).getString('ocrEngine'),
          'rapidocr',
        );
        expect(tester.takeException(), isNull);
      },
    );
  }
}
