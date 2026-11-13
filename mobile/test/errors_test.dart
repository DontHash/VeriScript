import 'dart:io';

import 'package:camera/camera.dart' show CameraException;
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/errors.dart';

void main() {
  const fallback = 'Could not do the thing. Try again.';

  test('app errors raised with StateError keep their sentence', () {
    expect(
      friendlyError(StateError('Select at least one page.'), fallback),
      'Select at least one page.',
    );
  });

  test('raw platform and unknown errors never reach the user', () {
    expect(
      friendlyError(PlatformException(code: 'x', message: 'boom'), fallback),
      fallback,
    );
    expect(friendlyError(Exception('Null check operator'), fallback), fallback);
    expect(friendlyError(ArgumentError('bad'), fallback), fallback);
  });

  test('a full disk is named, whatever the platform reports', () {
    expect(
      friendlyError(
        const FileSystemException('write', 'x', OSError('No space', 28)),
        fallback,
      ),
      storageFull,
    );
    expect(
      friendlyError(
        PlatformException(
          code: 'io',
          message: 'ENOSPC: No space left on device',
        ),
        fallback,
      ),
      storageFull,
    );
    expect(
      friendlyError(
        const FileSystemException('open', 'x', OSError('Not found', 2)),
        fallback,
      ),
      fallback,
    );
  });

  test('camera permission problems explain how to fix them', () {
    expect(
      friendlyError(CameraException('CameraAccessDenied', 'denied'), fallback),
      cameraPermission,
    );
    expect(
      friendlyError(CameraException('somethingElse', 'x'), fallback),
      fallback,
    );
  });
}
