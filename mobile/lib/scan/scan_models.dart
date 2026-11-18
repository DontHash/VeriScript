import 'dart:convert';

class ScanCameraCapabilities {
  const ScanCameraCapabilities({
    required this.probeVersion,
    required this.device,
    required this.manufacturer,
    required this.sdk,
    required this.cameras,
    required this.selected,
  });

  final int probeVersion;
  final String device;
  final String manufacturer;
  final int sdk;
  final List<ScanCameraInfo> cameras;
  final ScanCameraInfo? selected;

  factory ScanCameraCapabilities.fromMap(Map<String, dynamic> map) =>
      ScanCameraCapabilities(
        probeVersion: _int(map['probeVersion']),
        device: map['device'] as String? ?? 'unknown',
        manufacturer: map['manufacturer'] as String? ?? 'unknown',
        sdk: _int(map['sdk']),
        cameras: _maps(map['cameras']).map(ScanCameraInfo.fromMap).toList(),
        selected: map['selected'] is Map
            ? ScanCameraInfo.fromMap(
                Map<String, dynamic>.from(map['selected'] as Map),
              )
            : null,
      );

  String toDiagnosticString() {
    final buffer = StringBuffer()
      ..writeln('VeriScript camera probe v$probeVersion')
      ..writeln('Device: $manufacturer $device')
      ..writeln('Android SDK: $sdk')
      ..writeln('Cameras: ${cameras.length}');
    for (final camera in cameras) {
      buffer
        ..writeln()
        ..writeln(
          'Camera ${camera.id}: ${camera.facing} / ${camera.hardwareLevel}',
        );
      if (camera.error != null) {
        buffer.writeln('  error: ${camera.error}');
        continue;
      }
      buffer
        ..writeln(
          '  manual sensor: ${camera.manualSensor ? 'yes' : 'no'}, '
          'manual post: ${camera.manualPostProcessing ? 'yes' : 'no'}, '
          'RAW: ${camera.raw ? 'yes' : 'no'}, flash: ${camera.flash ? 'yes' : 'no'}',
        )
        ..writeln(
          '  AE compensation: ${camera.aeMin}..${camera.aeMax} '
          'step ${camera.aeStep.toStringAsFixed(3)}',
        )
        ..writeln('  AF modes: ${camera.afModes.join(', ')}')
        ..writeln('  AWB modes: ${camera.awbModes.join(', ')}')
        ..writeln('  sensor orientation: ${camera.sensorOrientation} deg');
      if (camera.pixelArray != null) {
        buffer.writeln(
          '  pixel array: ${camera.pixelArray!.width}x${camera.pixelArray!.height}',
        );
      }
      buffer.writeln('  JPEG sizes:');
      for (final size in camera.jpegSizes.take(12)) {
        buffer.writeln('    ${size.width}x${size.height} (${size.mp} MP)');
      }
    }
    return buffer.toString();
  }

  Map<String, dynamic> toJson() => {
    'probeVersion': probeVersion,
    'device': device,
    'manufacturer': manufacturer,
    'sdk': sdk,
    'cameras': cameras.map((camera) => camera.toJson()).toList(),
    'selected': selected?.toJson(),
  };

  String toJsonString() => const JsonEncoder.withIndent('  ').convert(toJson());
}

class ScanCameraInfo {
  const ScanCameraInfo({
    required this.id,
    required this.facing,
    required this.hardwareLevel,
    required this.capabilities,
    required this.manualSensor,
    required this.manualPostProcessing,
    required this.raw,
    required this.flash,
    required this.sensorOrientation,
    required this.aeMin,
    required this.aeMax,
    required this.aeMinIndex,
    required this.aeMaxIndex,
    required this.aeStep,
    required this.afModes,
    required this.awbModes,
    required this.focalLengths,
    required this.pixelArray,
    required this.jpegSizes,
    this.error,
  });

  final String id;
  final String facing;
  final String hardwareLevel;
  final List<String> capabilities;
  final bool manualSensor;
  final bool manualPostProcessing;
  final bool raw;
  final bool flash;
  final int sensorOrientation;
  final double aeMin;
  final double aeMax;
  final int aeMinIndex;
  final int aeMaxIndex;
  final double aeStep;
  final List<int> afModes;
  final List<int> awbModes;
  final List<double> focalLengths;
  final ScanSize? pixelArray;
  final List<ScanJpegSize> jpegSizes;
  final String? error;

  bool get isBack => facing == 'back';

  factory ScanCameraInfo.fromMap(Map<String, dynamic> map) => ScanCameraInfo(
    id: map['id'] as String? ?? '?',
    facing: map['facing'] as String? ?? 'unknown',
    hardwareLevel: map['hardwareLevel'] as String? ?? 'UNKNOWN',
    capabilities: _strings(map['capabilities']),
    manualSensor: map['manualSensor'] == true,
    manualPostProcessing: map['manualPostProcessing'] == true,
    raw: map['raw'] == true,
    flash: map['flash'] == true,
    sensorOrientation: _int(map['sensorOrientation']),
    aeMin: _double(map['aeMin']),
    aeMax: _double(map['aeMax']),
    aeMinIndex: _int(map['aeMinIndex']),
    aeMaxIndex: _int(map['aeMaxIndex']),
    aeStep: _double(map['aeStep']),
    afModes: _ints(map['afModes']),
    awbModes: _ints(map['awbModes']),
    focalLengths: _doubles(map['focalLengths']),
    pixelArray: map['pixelArray'] is Map
        ? ScanSize.fromMap(Map<String, dynamic>.from(map['pixelArray'] as Map))
        : null,
    jpegSizes: _maps(map['jpegSizes']).map(ScanJpegSize.fromMap).toList(),
    error: map['error'] as String?,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'facing': facing,
    'hardwareLevel': hardwareLevel,
    'capabilities': capabilities,
    'manualSensor': manualSensor,
    'manualPostProcessing': manualPostProcessing,
    'raw': raw,
    'flash': flash,
    'sensorOrientation': sensorOrientation,
    'aeMin': aeMin,
    'aeMax': aeMax,
    'aeMinIndex': aeMinIndex,
    'aeMaxIndex': aeMaxIndex,
    'aeStep': aeStep,
    'afModes': afModes,
    'awbModes': awbModes,
    'focalLengths': focalLengths,
    'pixelArray': pixelArray?.toJson(),
    'jpegSizes': jpegSizes.map((size) => size.toJson()).toList(),
    if (error != null) 'error': error,
  };
}

class ScanSize {
  const ScanSize(this.width, this.height);
  final int width;
  final int height;

  factory ScanSize.fromMap(Map<String, dynamic> map) =>
      ScanSize(_int(map['width']), _int(map['height']));

  Map<String, dynamic> toJson() => {'width': width, 'height': height};
}

class ScanJpegSize {
  const ScanJpegSize({
    required this.width,
    required this.height,
    required this.mp,
  });
  final int width;
  final int height;
  final double mp;

  factory ScanJpegSize.fromMap(Map<String, dynamic> map) => ScanJpegSize(
    width: _int(map['width']),
    height: _int(map['height']),
    mp: _double(map['megapixels']),
  );

  Map<String, dynamic> toJson() => {
    'width': width,
    'height': height,
    'megapixels': mp,
  };
}

int _int(Object? value) => (value as num?)?.toInt() ?? 0;
double _double(Object? value) => (value as num?)?.toDouble() ?? 0;
List<String> _strings(Object? value) =>
    value is List ? value.whereType<String>().toList() : const [];
List<int> _ints(Object? value) => value is List
    ? value.whereType<num>().map((e) => e.toInt()).toList()
    : const [];
List<double> _doubles(Object? value) => value is List
    ? value.whereType<num>().map((e) => e.toDouble()).toList()
    : const [];
List<Map<String, dynamic>> _maps(Object? value) => value is List
    ? value.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList()
    : const [];
