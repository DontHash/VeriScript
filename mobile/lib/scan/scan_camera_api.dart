import 'package:flutter/services.dart';

import 'scan_models.dart';

/// Phase 0 native API. In later phases this class grows open/close/capture,
/// but the channel name stays stable.
class ScanCameraApi {
  const ScanCameraApi();

  static const MethodChannel channel = MethodChannel('veriscript/scan_camera');

  Future<ScanCameraCapabilities> getCapabilities() async {
    final map = await channel.invokeMapMethod<String, dynamic>(
      'getCapabilities',
    );
    if (map == null) {
      throw StateError('The camera capability probe returned no data.');
    }
    return ScanCameraCapabilities.fromMap(map);
  }

  Future<Map<String, dynamic>> getDiagnostics() async {
    final map = await channel.invokeMapMethod<String, dynamic>(
      'getDiagnostics',
    );
    return map ?? const {};
  }
}
