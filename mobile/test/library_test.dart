import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/main.dart';

class LibraryStore extends DocumentStore {
  LibraryStore(this.documents) : super(Directory.systemTemp);
  final List<ScanDocument> documents;
  @override
  Future<List<ScanDocument>> list() async => List.of(documents);
  @override
  Future<void> save(ScanDocument doc) async {
    final index = documents.indexWhere((d) => d.id == doc.id);
    documents[index] = ScanDocument.fromJson(doc.toJson());
  }

  @override
  Future<void> delete(ScanDocument doc) async {
    documents.removeWhere((d) => d.id == doc.id);
  }
}

void main() {
  for (final dark in [false, true]) {
    testWidgets(
      'Files search, folder move and confirmed deletion work in ${dark ? 'dark' : 'light'} mode',
      (tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final book = ScanDocument(
          id: 'book',
          title: 'Lecture',
          pages: [],
          exports: ['saved.pdf'],
        );
        final store = LibraryStore([
          book,
          ScanDocument(id: 'invoice', title: 'Invoice', pages: []),
        ]);
        book.pages.add(
          ScanPage(
            id: 'p',
            source: 'missing',
            path: 'missing',
            recognized: true,
            lines: [
              {'text': 'नेपाल १२३'},
            ],
          ),
        );
        await store.save(book);
        SharedPreferences.setMockInitialValues({
          'theme': dark ? 2 : 1,
          'welcomed': true,
        });
        await tester.pumpWidget(
          VeriScriptApp(
            store: store,
            settings: await SharedPreferences.getInstance(),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Files'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextField), 'नेपाल');
        await tester.pumpAndSettle();
        expect(find.text('Lecture'), findsOneWidget);
        expect(find.text('1 page · 1 export'), findsOneWidget);
        expect(find.text('Invoice'), findsNothing);
        await tester.tap(find.text('Home'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Files'));
        await tester.pumpAndSettle();
        expect(
          tester.widget<TextField>(find.byType(TextField)).controller!.text,
          'नेपाल',
        );
        expect(find.text('Invoice'), findsNothing);
        await tester.enterText(find.byType(TextField), '');
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byTooltip('Manage Lecture'));
        await tester.tap(find.byTooltip('Manage Lecture'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Move to folder'));
        await tester.pumpAndSettle();
        await tester.enterText(
          find.descendant(
            of: find.byType(AlertDialog),
            matching: find.byType(TextField),
          ),
          'Study',
        );
        await tester.tap(find.text('Move'));
        await tester.pumpAndSettle();
        expect(
          (await store.list()).firstWhere((d) => d.id == book.id).folder,
          'Study',
        );
        await tester.tap(find.widgetWithText(FilterChip, 'Study'));
        await tester.pumpAndSettle();
        expect(find.text('Invoice'), findsNothing);
        // Delete hides the document at once; Undo brings it back untouched.
        await tester.tap(find.byTooltip('Manage Lecture'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Delete document'));
        await tester.pumpAndSettle();
        expect(find.text('Lecture'), findsNothing);
        expect(find.text('Deleted “Lecture”.'), findsOneWidget);
        await tester.tap(find.text('Undo'));
        await tester.pumpAndSettle();
        expect(find.text('Lecture'), findsOneWidget);
        expect(store.documents.any((d) => d.id == book.id), isTrue);
        // Without Undo, the files are deleted when the snackbar closes.
        await tester.tap(find.byTooltip('Manage Lecture'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Delete document'));
        await tester.pumpAndSettle();
        expect(store.documents.any((d) => d.id == book.id), isTrue);
        await tester.pump(const Duration(seconds: 7));
        await tester.pumpAndSettle();
        expect(store.documents.any((d) => d.id == book.id), isFalse);
        expect((await store.list()).single.title, 'Invoice');
        await tester.tap(find.widgetWithText(FilterChip, 'All'));
        await tester.pumpAndSettle();
        expect(find.text('Invoice'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
