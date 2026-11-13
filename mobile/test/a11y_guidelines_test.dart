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
  // Empty: every screen meets the guidelines. Only add an entry with an
  // audit item, and only for debt that existed before the gate.
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
        SharedPreferences.setMockInitialValues({
          'theme': dark ? 2 : 1,
          'welcomed': true,
        });
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

  // Audit A1 (WCAG 2.5.7): corners can be moved without dragging, both by
  // TalkBack custom actions and by the visible corner picker + arrows.
  testWidgets('crop corners can be moved without dragging', (tester) async {
    final handle = tester.ensureSemantics();
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final page = await _pageWithImage(tester);
    List<List<double>>? applied;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async => applied = await Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => CropScreen(page: page)),
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    for (var i = 1; i <= 4; i++) {
      final data = tester
          .getSemantics(find.bySemanticsLabel(RegExp('^Crop corner $i,')))
          .getSemanticsData();
      expect(data.customSemanticsActionIds, hasLength(4), reason: 'corner $i');
    }
    expect(
      tester
          .getSemantics(find.bySemanticsLabel(RegExp(r'^Crop corner 1,')))
          .getSemanticsData()
          .value,
      '3% across, 3% down',
    );

    // Pick corner 3 (bottom right) and move it up and left with the arrows.
    await tester.tap(find.byTooltip('Select the bottom right corner'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Move bottom right corner up'));
    await tester.tap(find.byTooltip('Move bottom right corner left'));
    await tester.tap(find.byTooltip('Move bottom right corner left'));
    await tester.pumpAndSettle();
    expect(
      find.text('Corner 3 (bottom right): 95% across, 96% down'),
      findsOneWidget,
    );

    await tester.tap(find.text('Apply'));
    await tester.pumpAndSettle();
    expect(applied![2][0], closeTo(.95, 1e-9));
    expect(applied![2][1], closeTo(.96, 1e-9));
    expect(applied![0], [.03, .03]);
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
