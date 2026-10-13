import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/editor.dart';
import 'package:veriscript_mobile/processing.dart';

class ReviewStore extends DocumentStore {
  ReviewStore(super.root);
  ScanDocument? saved;
  @override
  Future<void> save(ScanDocument doc) async {
    saved = ScanDocument.fromJson(jsonDecode(jsonEncode(doc.toJson())));
  }
}

void main() {
  testWidgets('Digit corrections need confirmation and retain both readings', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final root = Directory.systemTemp.createTempSync('veriscript-review-');
    addTearDown(() => root.deleteSync(recursive: true));
    final store = ReviewStore(root);
    final doc = ScanDocument(id: 'review', title: 'Review', pages: []);
    final image = File('${root.path}/page.png');
    image.writeAsBytesSync(
      base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ioAAAAASUVORK5CYII=',
      ),
    );
    final line = <String, dynamic>{
      'text': 'Total 128',
      'original': 'Total 128',
      'digitAlternative': 'Total 123',
      'digitCheck': 'conflict',
      'confidence': .99,
      'reviewed': false,
    };
    final page = ScanPage(
      id: 'page',
      source: image.path,
      path: image.path,
      recognized: true,
      lines: [line],
    );
    doc.pages.add(page);
    await tester.pumpWidget(
      MaterialApp(
        home: PageEditor(page: page, store: store, doc: doc),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Text'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Total 128'));
    await tester.pumpAndSettle();
    expect(find.text('Enlarged crop reading: Total 123'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'Total 123');
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(line['text'], 'Total 128');
    expect(needsReview(line), isTrue);
    await tester.tap(find.text('Total 128'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'Total 123');
    await tester.tap(find.text('Confirm'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final saved = store.saved!.pages.single.lines.single;
    expect(saved['text'], 'Total 123');
    expect(saved['original'], 'Total 128');
    expect(saved['digitAlternative'], 'Total 123');
    expect(needsReview(saved), isFalse);
  });
}
