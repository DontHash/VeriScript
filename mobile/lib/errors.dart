import 'dart:io';

import 'package:camera/camera.dart' show CameraException;
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show PlatformException;

import 'diagnostics.dart';

/// Turns an exception into one sentence a person can act on.
///
/// Raw exception text ("PlatformException(…)", "FileSystemException: …")
/// is never shown: it is logged for debugging and replaced by [fallback],
/// which callers phrase for the action that failed. Known causes (storage
/// full, camera permission off) get a specific message instead. Errors the
/// app raises itself with [StateError] already carry a human sentence and
/// are passed through.
String friendlyError(Object error, String fallback) {
  debugPrint('[error] $fallback — ${error.runtimeType}: $error');
  ErrorLog.record(fallback, error);
  if (error is StateError) return error.message;
  if (error is CameraException) return _cameraMessage(error.code, fallback);
  if (error is FileSystemException) return _fileMessage(error, fallback);
  if (error is PlatformException && _looksLikeStorage(error.message)) {
    return storageFull;
  }
  return fallback;
}

const storageFull =
    'Your phone is out of storage. Free some space, then try again.';
const cameraPermission =
    'Camera access is off. Allow it in Android Settings › Apps › VeriScript › '
    'Permissions, or import images instead.';

String _cameraMessage(String code, String fallback) {
  switch (code) {
    case 'CameraAccessDenied':
    case 'CameraAccessDeniedWithoutPrompt':
    case 'CameraAccessRestricted':
      return cameraPermission;
    case 'cameraNotReadable':
    case 'CameraNotReadable':
      return 'Another app is using the camera. Close it, then try again.';
    default:
      return fallback;
  }
}

String _fileMessage(FileSystemException error, String fallback) {
  // ENOSPC is 28 on Linux/Android; Windows test hosts report 112.
  final code = error.osError?.errorCode;
  if (code == 28 || code == 112 || _looksLikeStorage(error.osError?.message)) {
    return storageFull;
  }
  return fallback;
}

bool _looksLikeStorage(String? message) {
  final text = (message ?? '').toLowerCase();
  return text.contains('no space') || text.contains('disk full');
}
