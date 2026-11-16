import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/review.dart';

/// docs/TECH_UPGRADE_PLAN.md E5 from the review screen: "Move selected pages
/// to a new document" and "Add pages from another document".
void main() {
  late Directory root;
  late DocumentStore store;
  late SharedPreferences settings;

  setUp(() async {
    root = Directory.systemTemp.createTempSync('vs-review-pages-');
    store = DocumentStore(root);
    SharedPreferences.setMockInitialValues({});
    settings = await SharedPreferences.getInstance();
  });
  tearDown(() {
    try {
      root.deleteSync(recursive: true);
    } on FileSystemException {
      // Windows: an image the screen still shows keeps its file open.
    }
  });

  Future<ScanDocument> docWith(String title, List<String> ids) async {
    final doc = await store.create(title);
    for (final id in ids) {
      final path = '${store.directory(doc)}/page_$id.png';
      File(path).writeAsBytesSync(img.encodePng(img.Image(width: 8, height: 8)));
      doc.pages.add(ScanPage(id: id, source: path, path: path, recognized: true,
          lines: [{'text': 'page $id'}]));
    }
    await store.save(doc);
    return doc;
  }

  Future<void> open(WidgetTester tester, ScanDocument doc) async {
    tester.view.physicalSize = const Size(400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
      home: ReviewScreen(doc: doc, store: store, settings: settings),
    ));
    await tester.pumpAndSettle();
  }

  Future<void> menu(WidgetTester tester, String item) async {
    await tester.tap(find.byTooltip('Document actions'));
    await tester.pumpAndSettle();
    await tester.tap(find.text(item));
    await tester.pumpAndSettle();
  }

  /// Real file work runs outside the test clock: let it run until [until]
  /// shows up (or about 10 s pass).
  Future<void> settle(WidgetTester tester, [Finder? until]) async {
    for (var i = 0; i < 200; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await tester.pump(const Duration(milliseconds: 100));
      if (until != null && until.evaluate().isNotEmpty) return;
      if (until == null && i >= 10) return;
    }
  }

  testWidgets('selected pages move to a new document', (tester) async {
    late ScanDocument doc;
    await tester.runAsync(() async => doc = await docWith('Ward 7', ['1', '2', '3']));
    doc.pages.first.included = false;
    await open(tester, doc);
    await menu(tester, 'Move selected pages to a new document');
    expect(find.text('Move 2 pages to a new document'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'Ward 7 annex');
    await tester.tap(find.text('Move'));
    await settle(tester, find.text('Moved 2 pages to “Ward 7 annex”.'));
    expect(find.text('Moved 2 pages to “Ward 7 annex”.'), findsOneWidget);
    expect(doc.pages.map((p) => p.id), ['1']);
    late List<ScanDocument> all;
    await tester.runAsync(() async => all = await store.list());
    final annex = all.singleWhere((d) => d.title == 'Ward 7 annex');
    expect(annex.pages.map((p) => p.text), ['page 2', 'page 3']);
  });

  testWidgets('moving every page is refused with a reason', (tester) async {
    late ScanDocument doc;
    await tester.runAsync(() async => doc = await docWith('A', ['1', '2']));
    await open(tester, doc);
    await menu(tester, 'Move selected pages to a new document');
    expect(find.text('Select the pages to move. At least one page must stay.'), findsOneWidget);
    expect(doc.pages.length, 2);
  });

  testWidgets('pages from another document are added at the end', (tester) async {
    late ScanDocument doc;
    await tester.runAsync(() async {
      await docWith('Receipts March', ['8', '9']);
      doc = await docWith('Receipts', ['1']);
    });
    await open(tester, doc);
    await menu(tester, 'Add pages from another document');
    await settle(tester, find.text('Receipts March'));
    await tester.pumpAndSettle(); // let the sheet finish sliding in
    await tester.tap(find.text('Receipts March'));
    await settle(tester, find.text('Added 2 pages from “Receipts March”.'));
    expect(find.text('Added 2 pages from “Receipts March”.'), findsOneWidget);
    expect(doc.pages.map((p) => p.text), ['page 1', 'page 8', 'page 9']);
  });
}
