import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
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

/// Lets real file I/O finish. The editor shows a spinner while it saves, and
/// a spinner never settles, so wait (in real time, up to 10 s) until it is
/// gone instead of assuming a fixed delay — that assumption flaked when the
/// suite ran test files in parallel on a busy machine.
Future<void> settleDisk(WidgetTester tester) async {
  for (var i = 0; i < 250; i++) {
    await tester.pump();
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 40)),
    );
    if (i >= 9 && find.byType(CircularProgressIndicator).evaluate().isEmpty) {
      break;
    }
  }
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'Image edit requires approval and saved corrections recover after reload',
    (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final root = Directory.systemTemp.createTempSync('veriscript-transform-');
      addTearDown(() => root.deleteSync(recursive: true));
      final initial = (await tester.runAsync(() async {
        final store = DocumentStore(root);
        return (store, await store.create('Protected'));
      }))!;
      final store = initial.$1, doc = initial.$2;
      final image = File('${store.directory(doc)}/page.png')
        ..writeAsBytesSync(img.encodePng(img.Image(width: 8, height: 8)));
      final page = ScanPage(
        id: 'page',
        source: image.path,
        path: image.path,
        width: 900,
        height: 1200,
        recognized: true,
        lines: [
          {
            'text': 'Corrected १२३',
            'original': 'Original १२८',
            'reviewed': true,
          },
        ],
      );
      doc.pages.add(page);
      await tester.runAsync(() => store.save(doc));
      var calls = 0;
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(native, (call) async {
        calls++;
        image.copySync(call.arguments['out']);
        return {'path': call.arguments['out'], 'width': 1200, 'height': 900};
      });
      addTearDown(() => messenger.setMockMethodCallHandler(native, null));
      await tester.pumpWidget(
        MaterialApp(
          home: PageEditor(page: page, store: store, doc: doc),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Rotate'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(calls, 0);
      expect(page.text, 'Corrected १२३');
      await tester.tap(find.text('Rotate'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Continue'));
      await settleDisk(tester);
      expect(page.recognized, false);
      expect(page.previousVersion, isNotNull);
      final reloaded = (await tester.runAsync(store.list))!.single;
      await tester.pumpWidget(
        MaterialApp(
          home: PageEditor(
            key: const ValueKey('reloaded'),
            page: reloaded.pages.single,
            store: store,
            doc: reloaded,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Restore previous text'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Restore'));
      await settleDisk(tester);
      final restored = (await tester.runAsync(store.list))!.single.pages.single;
      expect(restored.path, image.path);
      expect(restored.width, 900);
      expect(restored.height, 1200);
      expect(restored.text, 'Corrected १२३');
      expect(restored.lines.single['reviewed'], true);
      expect(restored.previousVersion, isNull);
      expect(tester.takeException(), isNull);
    },
  );
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
    image.writeAsBytesSync(img.encodePng(img.Image(width: 8, height: 8)));
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
