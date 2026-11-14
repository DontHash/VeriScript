import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'documents.dart';

/// Local diagnostics for bug reports (docs/TECH_UPGRADE_PLAN.md, A6).
///
/// Nothing is sent anywhere. The report is shown to the person first and
/// only leaves the phone if they copy it themselves. It holds versions,
/// settings, counts and recent error types: no document titles, page text
/// or images.
const appVersion = '0.1.0';

class ErrorLog {
  ErrorLog._();
  static final _entries = <String>[];
  static const _max = 30;

  static void record(String action, Object error) {
    final when = DateTime.now().toUtc().toIso8601String().substring(0, 19);
    var detail = '$error'.replaceAll(RegExp(r'\s+'), ' ');
    // Paths can contain a document's folder or a picked file's name.
    detail = detail.replaceAll(RegExp(r"(/[^\s,:'\x22)]+)+"), '<path>');
    if (detail.length > 160) detail = '${detail.substring(0, 160)}…';
    _entries.add('$when $action — ${error.runtimeType}: $detail');
    if (_entries.length > _max) _entries.removeAt(0);
  }

  static List<String> get entries => List.unmodifiable(_entries);

  @visibleForTesting
  static void clear() => _entries.clear();
}

Future<int> _folderBytes(Directory dir) async {
  var total = 0;
  if (!await dir.exists()) return 0;
  await for (final entry in dir.list(recursive: true, followLinks: false)) {
    if (entry is File) {
      try {
        total += await entry.length();
      } on FileSystemException {
        // Removed while counting.
      }
    }
  }
  return total;
}

/// Plain-text report: safe to read aloud, paste into an email or an issue.
Future<String> diagnosticsReport(
  SharedPreferences settings,
  DocumentStore store,
) async {
  final docs = await store.list();
  final pages = docs.expand((d) => d.pages).toList();
  final bytes = await _folderBytes(store.root);
  String flag(String key, {bool fallback = true}) =>
      (settings.getBool(key) ?? fallback) ? 'on' : 'off';
  final errors = ErrorLog.entries;
  return [
    'VeriScript $appVersion (Android, offline)',
    'OS: ${Platform.operatingSystem} ${Platform.operatingSystemVersion}',
    'Processors: ${Platform.numberOfProcessors} · locale ${Platform.localeName}',
    'Dart: ${Platform.version.split(' ').first}',
    '',
    'Settings: language ${settings.getString('language') ?? 'ne'} · '
        'reader ${settings.getString('ocrEngine') ?? 'mlkit'} · '
        'alignment ${flag('align')} · enhancement ${flag('enhance')} · '
        'digit checks ${flag('digits')} · orientation ${flag('rotate')}',
    'Library: ${docs.length} documents · ${pages.length} pages · '
        '${pages.where((p) => p.recognized).length} recognized · '
        '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB',
    '',
    if (errors.isEmpty) 'Recent errors: none' else 'Recent errors (newest last):',
    ...errors,
  ].join('\n');
}
