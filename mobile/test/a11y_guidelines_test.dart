// Accessibility gate (docs/UX_A11Y_AUDIT.md, Phase 0).
//
// Runs Flutter's built-in guidelines on every main screen in both themes:
//   * androidTapTargetGuideline   — tappable things are at least 48x48 dp
//   * labeledTapTargetGuideline   — tappable things have a semantic label
//   * textContrastGuideline       — text meets WCAG AA contrast
//
// Ratchet: entries in `knownDebt` are expected to FAIL today and are asserted
// with `doesNotMeetGuideline`. When a fix lands that test fails with
// "fixed — remove from knownDebt", so the improvement is locked in.
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/editor.dart';
import 'package:veriscript_mobile/main.dart';

class _Store extends DocumentStore {
  _Store(this.documents) : super(Directory.systemTemp);
  final List<ScanDocument> documents;
  @override
  Future<List<ScanDocument>> list() async => List.of(documents);
}

const guidelines = <String, AccessibilityGuideline>{
  'tap-target': androidTapTargetGuideline,
  'labeled': labeledTapTargetGuideline,
  'contrast': textContrastGuideline,
};

/// `screen/theme/guideline` keys that fail today, with the audit item.
const knownDebt = <String, String>{
  // Amber "Apply" text button on paper is 1.92:1 (same root cause as web W1).
  'crop/light/contrast': 'audit W1/A7: amber TextButton on light paper',
};

Future<void> checkAll(WidgetTester tester, String screen, String theme) async {
  for (final entry in guidelines.entries) {
    final key = '$screen/$theme/${entry.key}';
    if (knownDebt.containsKey(key)) {
      await expectLater(
        tester,
        doesNotMeetGuideline(entry.value),
        reason: 'fixed — remove "$key" from knownDebt (${knownDebt[key]})',
      );
    } else {
      await expectLater(tester, meetsGuideline(entry.value), reason: key);
    }
  }
}

void main() {
  for (final dark in [false, true]) {
    final theme = dark ? 'dark' : 'light';
    for (final tab in ['Home', 'Files', 'Settings']) {
      testWidgets('library $tab meets a11y guidelines ($theme)', (
        tester,
      ) async {
        final handle = tester.ensureSemantics();
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        SharedPreferences.setMockInitialValues({'theme': dark ? 2 : 1});
        await tester.pumpWidget(
          VeriScriptApp(
            settings: await SharedPreferences.getInstance(),
            store: _Store([
              ScanDocument(id: 'a', title: 'Invoice', pages: []),
              ScanDocument(id: 'b', title: 'Lecture notes', pages: []),
            ]),
          ),
        );
        await tester.pumpAndSettle();
        if (tab != 'Home') {
          await tester.tap(find.text(tab));
          await tester.pumpAndSettle();
        }
        await checkAll(tester, 'library-${tab.toLowerCase()}', theme);
        handle.dispose();
      });
    }

    testWidgets('crop screen meets a11y guidelines ($theme)', (tester) async {
      final handle = tester.ensureSemantics();
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final page = await _pageWithImage(tester);
      await tester.pumpWidget(
        MaterialApp(
          theme: studioTheme(dark ? Brightness.dark : Brightness.light),
          home: CropScreen(page: page),
        ),
      );
      await tester.pumpAndSettle();
      await checkAll(tester, 'crop', theme);
      handle.dispose();
    });
  }

  // Audit A1 (WCAG 2.5.7): a corner must be movable without dragging, so
  // TalkBack and switch-access users can crop. Known debt today: flip the
  // expectation to `isTrue` when the semantic actions land.
  testWidgets('crop corners can be moved without dragging (known debt A1)', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    final page = await _pageWithImage(tester);
    await tester.pumpWidget(MaterialApp(home: CropScreen(page: page)));
    await tester.pumpAndSettle();
    final data = tester
        .getSemantics(find.bySemanticsLabel(RegExp(r'^Crop corner 1')))
        .getSemanticsData();
    final movable =
        data.hasAction(SemanticsAction.increase) ||
        data.hasAction(SemanticsAction.decrease) ||
        (data.customSemanticsActionIds?.isNotEmpty ?? false);
    expect(
      movable,
      isFalse,
      reason: 'fixed — change this expectation to isTrue (audit A1)',
    );
    handle.dispose();
  });
}

Future<ScanPage> _pageWithImage(WidgetTester tester) async {
  final dir = (await tester.runAsync(
    () async => Directory.systemTemp.createTemp('veriscript-a11y-'),
  ))!;
  addTearDown(() {
    try {
      dir.deleteSync(recursive: true);
    } on FileSystemException {
      // Windows keeps the decoded image open until the engine releases it.
    }
  });
  final file = File('${dir.path}/page.png')
    ..writeAsBytesSync(img.encodePng(img.Image(width: 30, height: 40)));
  return ScanPage(
    id: 'p',
    source: file.path,
    path: file.path,
    width: 300,
    height: 400,
  );
}
