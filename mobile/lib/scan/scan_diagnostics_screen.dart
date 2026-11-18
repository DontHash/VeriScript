import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'scan_camera_api.dart';
import 'scan_models.dart';

/// Read-only Phase 0 diagnostics. It never opens the camera or takes a photo.
class ScanDiagnosticsScreen extends StatefulWidget {
  const ScanDiagnosticsScreen({super.key, this.api = const ScanCameraApi()});

  final ScanCameraApi api;

  @override
  State<ScanDiagnosticsScreen> createState() => _ScanDiagnosticsScreenState();
}

class _ScanDiagnosticsScreenState extends State<ScanDiagnosticsScreen> {
  late Future<ScanCameraCapabilities> _future;
  ScanCameraCapabilities? _capabilities;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<ScanCameraCapabilities> _load() async {
    final capabilities = await widget.api.getCapabilities();
    if (mounted) setState(() => _capabilities = capabilities);
    return capabilities;
  }

  Future<void> _refresh() async {
    setState(() => _future = _load());
    await _future;
  }

  Future<void> _copy(String label, String value) async {
    await Clipboard.setData(ClipboardData(text: value));
    if (!mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text('$label copied')));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Camera diagnostics'),
        actions: [
          IconButton(
            tooltip: 'Copy JSON report',
            onPressed: _capabilities == null
                ? null
                : () => _copy('Camera report', _capabilities!.toJsonString()),
            icon: const Icon(Icons.copy_all_outlined),
          ),
        ],
      ),
      body: FutureBuilder<ScanCameraCapabilities>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      'Could not read camera capabilities.',
                      style: theme.textTheme.titleMedium,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 8),
                    Text('${snapshot.error}', textAlign: TextAlign.center),
                    const SizedBox(height: 16),
                    FilledButton.icon(
                      onPressed: _refresh,
                      icon: const Icon(Icons.refresh),
                      label: const Text('Try again'),
                    ),
                  ],
                ),
              ),
            );
          }
          final capabilities = snapshot.data!;
          return RefreshIndicator(
            onRefresh: _refresh,
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                Text('Read-only probe', style: theme.textTheme.displayMedium),
                const SizedBox(height: 8),
                const Text(
                  'This screen reads the camera hardware capabilities only. '
                  'It does not open the camera, take photos, or use the network.',
                ),
                const SizedBox(height: 20),
                _summaryCard(context, capabilities),
                const SizedBox(height: 16),
                ...capabilities.cameras.map(
                  (camera) => Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: _cameraCard(context, camera),
                  ),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: () =>
                      _copy('Camera report', capabilities.toDiagnosticString()),
                  icon: const Icon(Icons.copy_outlined),
                  label: const Text('Copy readable report'),
                ),
                const SizedBox(height: 8),
                Text(
                  'Phase 0 checks the hardware before the native scan camera is built. '
                  'Actual stream combinations and capture sizes still need device tests.',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _summaryCard(
    BuildContext context,
    ScanCameraCapabilities capabilities,
  ) {
    final selected = capabilities.selected;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Device', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            Text('${capabilities.manufacturer} ${capabilities.device}'),
            Text('Android SDK ${capabilities.sdk}'),
            Text('${capabilities.cameras.length} camera(s) reported'),
            if (selected != null) ...[
              const SizedBox(height: 8),
              Text(
                'Selected back camera: ${selected.id} '
                '(${selected.hardwareLevel})',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _cameraCard(BuildContext context, ScanCameraInfo camera) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Camera ${camera.id} - ${camera.facing}',
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 2),
            Text('Hardware level: ${camera.hardwareLevel}'),
            if (camera.error != null) ...[
              const SizedBox(height: 8),
              Text('Probe error: ${camera.error}'),
            ] else ...[
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _tag(
                    context,
                    camera.manualSensor ? 'manual sensor' : 'no manual sensor',
                  ),
                  _tag(
                    context,
                    camera.manualPostProcessing
                        ? 'manual post-processing'
                        : 'no manual post-processing',
                  ),
                  _tag(context, camera.raw ? 'RAW' : 'no RAW'),
                  _tag(context, camera.flash ? 'flash' : 'no flash'),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                'AE compensation: ${camera.aeMin.toStringAsFixed(1)} to '
                '${camera.aeMax.toStringAsFixed(1)}, step '
                '${camera.aeStep.toStringAsFixed(3)}',
              ),
              Text(
                'AF modes: ${camera.afModes.join(', ')}  |  '
                'AWB modes: ${camera.awbModes.join(', ')}',
              ),
              Text('Sensor orientation: ${camera.sensorOrientation} degrees'),
              if (camera.pixelArray != null)
                Text(
                  'Pixel array: ${camera.pixelArray!.width} x '
                  '${camera.pixelArray!.height}',
                ),
              const SizedBox(height: 10),
              Text('JPEG sizes', style: theme.textTheme.titleSmall),
              const SizedBox(height: 4),
              ...camera.jpegSizes
                  .take(12)
                  .map(
                    (size) => Text(
                      '${size.width} x ${size.height}  -  ${size.mp} MP',
                    ),
                  ),
              if (camera.capabilities.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text(
                  'Capabilities: ${camera.capabilities.join(', ')}',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }

  Widget _tag(BuildContext context, String label) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(label, style: Theme.of(context).textTheme.bodySmall),
    );
  }
}
