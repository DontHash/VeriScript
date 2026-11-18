import 'dart:async';

import 'package:flutter/services.dart';

/// Keeps long page work alive while the user is in another app
/// (docs/TECH_UPGRADE_PLAN.md, A3).
///
/// Android may stop a backgrounded app to free memory, which used to end a
/// long recognition batch half way. While work runs longer than [delay], a
/// foreground service shows its progress as a notification, which tells the
/// system the work matters. Short work never shows a notification.
///
/// Drafts are saved after every page regardless, so pages finished before
/// any interruption are kept and "Recognize unread pages" continues.
class ProcessingNotice {
  ProcessingNotice(
    this.title,
    this._read, {
    this.delay = const Duration(seconds: 2),
    MethodChannel? channel,
  }) : _channel = channel ?? const MethodChannel('veriscript/background');

  final String title;

  /// Current (status text, fraction 0..1 or null when unknown).
  final (String, double?) Function() _read;
  final Duration delay;
  final MethodChannel _channel;
  Timer? _timer;
  bool _started = false;
  String? _last;
  final _clock = Stopwatch();

  void begin() {
    _clock.start();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  Future<void> _tick() async {
    if (_clock.elapsed < delay) return;
    final (text, fraction) = _read();
    final permille = fraction == null ? -1 : (fraction * 1000).round();
    final key = '$text|$permille';
    if (_started && key == _last) return;
    _last = key;
    final method = _started ? 'update' : 'start';
    _started = true;
    await _call(method, {'title': title, 'text': text, 'permille': permille});
  }

  Future<void> end() async {
    _timer?.cancel();
    _timer = null;
    if (_started) await _call('stop', const {});
    _started = false;
  }

  Future<void> _call(String method, Map<String, Object> args) async {
    try {
      await _channel.invokeMethod<void>(method, args);
    } on MissingPluginException {
      // Tests and non-Android hosts: nothing to keep alive.
    } on PlatformException {
      // The work continues without the notification.
    }
  }
}
