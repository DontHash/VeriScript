import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/background.dart';

/// docs/TECH_UPGRADE_PLAN.md A3: long work holds a progress notification;
/// short work never shows one.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('veriscript/background-test');
  late List<MethodCall> calls;

  setUp(() {
    calls = [];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      return null;
    });
  });

  test('short work never starts the service', () async {
    final keep = ProcessingNotice('Doc', () => ('Reading', null), channel: channel)..begin();
    await Future<void>.delayed(const Duration(milliseconds: 1200));
    await keep.end();
    expect(calls, isEmpty);
  });

  test('long work starts once, updates on change, stops at the end', () async {
    var status = 'Page 1 of 3';
    double? fraction = 0;
    final keep = ProcessingNotice(
      'Receipts',
      () => (status, fraction),
      delay: Duration.zero,
      channel: channel,
    )..begin();
    await Future<void>.delayed(const Duration(milliseconds: 1100));
    expect(calls.map((c) => c.method), ['start']);
    expect(calls.single.arguments, {'title': 'Receipts', 'text': 'Page 1 of 3', 'permille': 0});

    await Future<void>.delayed(const Duration(milliseconds: 1000));
    expect(calls.length, 1, reason: 'unchanged progress is not re-sent');

    status = 'Page 2 of 3';
    fraction = .5;
    await Future<void>.delayed(const Duration(milliseconds: 1000));
    expect(calls.last.method, 'update');
    expect(calls.last.arguments['permille'], 500);

    await keep.end();
    expect(calls.last.method, 'stop');
  });

  test('a missing platform side is harmless', () async {
    final keep = ProcessingNotice(
      'Doc',
      () => ('x', null),
      delay: Duration.zero,
      channel: const MethodChannel('veriscript/not-registered'),
    )..begin();
    await Future<void>.delayed(const Duration(milliseconds: 1100));
    await keep.end();
  });
}
