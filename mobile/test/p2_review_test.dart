import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/exports.dart';
import 'package:veriscript_mobile/main.dart';
import 'package:veriscript_mobile/review.dart';
import 'package:veriscript_mobile/editor.dart';
import 'package:image/image.dart' as img;

Future<void> reveal(
  WidgetTester tester,
  Finder finder, {
  double delta = 150,
}) async {
  if (finder.evaluate().isEmpty) {
    await tester.scrollUntilVisible(
      finder,
      delta,
      scrollable: find.byType(Scrollable).first,
    );
  }
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

class PreviewStore extends DocumentStore {
  PreviewStore() : super(Directory.systemTemp);
  ScanDocument? saved;
  @override
  Future<void> save(ScanDocument doc) async {
    saved = ScanDocument.fromJson(doc.toJson());
  }
}

void main() {
  for (final count in [1, 150]) {
    testWidgets('Unread review remains scrollable with $count pages', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(320, 720);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      SharedPreferences.setMockInitialValues({});
      final settings = await SharedPreferences.getInstance();
      await tester.pumpWidget(
        MaterialApp(
          theme: studioTheme(Brightness.dark),
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: TextScaler.linear(count == 1 ? 2 : 1)),
            child: child!,
          ),
          home: ReviewScreen(
            store: PreviewStore(),
            settings: settings,
            doc: ScanDocument(
              id: 'unread',
              title: 'Book',
              pages: [
                for (var i = 0; i < count; i++)
                  ScanPage(id: '$i', source: 'missing', path: 'missing'),
              ],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.text(
          count == 1 ? 'Recognize 1 unread page' : 'Recognize 150 unread pages',
        ),
        findsOneWidget,
      );
      expect(find.byType(Image).evaluate().length, lessThan(12));
      expect(tester.takeException(), isNull);
      await tester.drag(find.byType(CustomScrollView), const Offset(0, -200));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      if (count == 1) {
        await reveal(tester, find.text('Export selected pages'));
        await tester.tap(find.text('Export selected pages'));
        await tester.pumpAndSettle();
        expect(find.text('Choose an export'), findsOneWidget);
        expect(tester.takeException(), isNull);
      }
    });
  }
  for (final dark in [false, true]) {
    for (final scale in [1.0, 1.6]) {
      testWidgets(
        'Review selection, ordering, details and export guidance: dark=$dark, text=$scale',
        (tester) async {
          tester.view.physicalSize = const Size(360, 800);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          SharedPreferences.setMockInitialValues({});
          final settings = await SharedPreferences.getInstance();
          final store = PreviewStore();
          final image = File(
            '${Directory.systemTemp.createTempSync('p2-review-').path}/page.png',
          );
          image.writeAsBytesSync(img.encodePng(img.Image(width: 8, height: 8)));
          addTearDown(() => image.parent.deleteSync(recursive: true));
          final doc = ScanDocument(
            id: 'preview',
            title: 'Lecture',
            warnings: ['The book may be incomplete.'],
            pages: [
              for (var i = 1; i <= 2; i++)
                ScanPage(
                  id: 'p$i',
                  source: image.path,
                  path: image.path,
                  recognized: true,
                  note: 'Original kept; image enhanced.',
                  lines: [
                    {
                      'text': 'नेपाल १२३',
                      'digitCheck': 'conflict',
                      'reviewed': false,
                    },
                  ],
                ),
            ],
          );
          Widget app() => MaterialApp(
            theme: studioTheme(dark ? Brightness.dark : Brightness.light),
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(
                context,
              ).copyWith(textScaler: TextScaler.linear(scale)),
              child: child!,
            ),
            home: ReviewScreen(doc: doc, store: store, settings: settings),
          );
          await tester.pumpWidget(app());
          await tester.pumpAndSettle();
          expect(find.text('The book may be incomplete.'), findsOneWidget);
          await tester.scrollUntilVisible(
            find.byKey(const ValueKey('preview-p1')),
            150,
            scrollable: find.byType(Scrollable).first,
          );
          expect(find.byType(SliverGrid), findsOneWidget);
          final delegate =
              tester.widget<SliverGrid>(find.byType(SliverGrid)).gridDelegate
                  as SliverGridDelegateWithFixedCrossAxisCount;
          expect(delegate.crossAxisCount, scale == 1 ? 2 : 1);
          expect(find.text('Original kept; image enhanced.'), findsNothing);
          expect(find.text('1 line to review'), findsWidgets);
          expect(tester.takeException(), isNull);

          await reveal(tester, find.byTooltip('Move page 1 down'));
          await tester.tap(find.byTooltip('Move page 1 down'));
          await tester.pumpAndSettle();
          expect(doc.pages.map((p) => p.id), ['p2', 'p1']);
          final card = find.ancestor(
            of: find.byKey(const ValueKey('preview-p2')),
            matching: find.byType(Card),
          );
          final checkbox = find.descendant(
            of: card,
            matching: find.byType(Checkbox),
          );
          await reveal(tester, checkbox);
          await tester.tap(checkbox);
          await tester.pumpAndSettle();
          expect(store.saved!.selected.map((p) => p.id), ['p1']);
          expect(find.text('Excluded from export'), findsOneWidget);
          await reveal(tester, find.byTooltip('List view'), delta: -150);
          await tester.tap(find.byTooltip('List view'));
          await tester.pumpAndSettle();
          expect(find.byType(ReorderableListView), findsOneWidget);
          expect(settings.getBool('reviewGrid'), false);
          await reveal(tester, find.byTooltip('Move page 1 down'));
          await tester.tap(find.byTooltip('Move page 1 down'));
          await tester.pumpAndSettle();
          expect(store.saved!.pages.map((p) => p.id), ['p1', 'p2']);
          expect(store.saved!.selected.map((p) => p.id), ['p1']);

          await reveal(tester, find.text('Capture details'), delta: -150);
          await tester.tap(find.text('Capture details'));
          await tester.pumpAndSettle();
          expect(find.text('Original kept; image enhanced.'), findsOneWidget);
          expect(find.text('Pages 1, 2'), findsOneWidget);
          await tester.tap(find.byTooltip('Close capture details'));
          await tester.pumpAndSettle();
          await tester.tap(find.text('Export selected pages'));
          await tester.pumpAndSettle();
          expect(find.text(ExportKind.searchablePdf.guidance), findsOneWidget);
          await tester.scrollUntilVisible(
            find.text(ExportKind.digitalPdf.label),
            100,
            scrollable: find.byType(Scrollable).last,
          );
          expect(find.text(ExportKind.digitalPdf.guidance), findsOneWidget);
          expect(tester.takeException(), isNull);
          Navigator.of(tester.element(find.text('Choose an export'))).pop();
          await tester.pumpAndSettle();

          await tester.pumpWidget(const SizedBox());
          await tester.pumpWidget(app());
          await tester.pumpAndSettle();
          expect(find.byType(ReorderableListView), findsOneWidget);
          final previewImage = find.descendant(
            of: find.byKey(const ValueKey('preview-p1')),
            matching: find.byType(Image),
          );
          await reveal(tester, previewImage);
          await tester.tap(previewImage);
          await tester.pumpAndSettle();
          expect(find.byType(PageEditor), findsOneWidget);
          expect(tester.takeException(), isNull);
        },
      );
    }
  }
}
