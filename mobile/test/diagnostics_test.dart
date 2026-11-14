import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:veriscript_mobile/diagnostics.dart';
import 'package:veriscript_mobile/documents.dart';
import 'package:veriscript_mobile/errors.dart';

/// docs/TECH_UPGRADE_PLAN.md A6: a local report with no document content.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('report has counts and settings but no titles or text', () async {
    SharedPreferences.setMockInitialValues({'language': 'en', 'digits': false});
    final settings = await SharedPreferences.getInstance();
    final root = await Directory.systemTemp.createTemp('vs-diag-');
    addTearDown(() => root.delete(recursive: true));
    final store = DocumentStore(root);
    final doc = await store.create('Land record of Ram Bahadur');
    doc.pages.add(ScanPage(
      id: '1',
      source: 's',
      path: 'p',
      recognized: true,
      lines: [
        {'text': 'Plot 4471 owner Ram Bahadur'},
      ],
    ));
    await store.save(doc);
    ErrorLog.clear();
    friendlyError(
      const FileSystemException('Cannot open', '/data/user/0/app/documents/123/page_9.jpg'),
      'The page could not be saved.',
    );

    final report = await diagnosticsReport(settings, store);
    expect(report, contains('VeriScript $appVersion'));
    expect(report, contains('language en'));
    expect(report, contains('digit checks off'));
    expect(report, contains('1 documents · 1 pages · 1 recognized'));
    expect(report, contains('The page could not be saved. — FileSystemException'));
    expect(report, isNot(contains('Ram Bahadur')));
    expect(report, isNot(contains('4471')));
    expect(report, isNot(contains('page_9.jpg')));
  });

  test('error log keeps the 30 newest entries', () {
    ErrorLog.clear();
    for (var i = 0; i < 40; i++) {
      ErrorLog.record('step $i', StateError('x'));
    }
    expect(ErrorLog.entries.length, 30);
    expect(ErrorLog.entries.first, contains('step 10 '));
    expect(ErrorLog.entries.last, contains('step 39 '));
  });
}
