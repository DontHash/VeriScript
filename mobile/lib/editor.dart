import 'dart:io';
import 'package:flutter/material.dart';
import 'documents.dart';
import 'processing.dart';

class PageEditor extends StatefulWidget {
  const PageEditor({
    super.key,
    required this.page,
    required this.store,
    required this.doc,
    this.language = 'ne',
    this.autoRotate = true,
    this.checkDigits = true,
  });
  final ScanPage page;
  final DocumentStore store;
  final ScanDocument doc;
  final String language;
  final bool autoRotate, checkDigits;
  @override
  State<PageEditor> createState() => _PageEditorState();
}

class _PageEditorState extends State<PageEditor> {
  ScanPage get page => widget.page;
  bool busy = false;
  int revision = 0;
  bool showOriginal = false;
  String status = '';
  OfflineProcessor? processor;

  Future<bool> confirmReplacement(String action) async {
    if (!page.recognized) return true;
    return await showDialog<bool>(
          context: context,
          builder: (_) => AlertDialog(
            title: Text(action),
            content: const Text(
              'This replaces the current text, including your corrections. '
              'One previous version of the image and text will be kept on this phone. '
              'Use Restore previous text to recover it.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Cancel'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Continue'),
              ),
            ],
          ),
        ) ??
        false;
  }

  void message(String text) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
    }
  }

  Future<void> recognize() async {
    if (busy ||
        !await confirmReplacement('Recognize this page again?') ||
        !mounted) {
      return;
    }
    final before = page.snapshot(), previous = page.previousVersion;
    final worker = OfflineProcessor(widget.language);
    processor = worker;
    setState(() {
      busy = true;
      status = 'Reading text';
    });
    try {
      await worker.recognize(
        page,
        autoRotate: widget.autoRotate,
        checkDigits: widget.checkDigits,
        onProgress: (stage) {
          if (mounted) setState(() => status = stage);
        },
      );
      await widget.store.save(widget.doc);
      if (page.lines.isEmpty) {
        message('No text detected. Try cropping the page or a sharper photo.');
      }
      showOriginal = false;
      revision++;
    } catch (e) {
      page.applySnapshot(before);
      page.previousVersion = previous;
      message(
        worker.cancelled
            ? 'Stopped. Your previous image and text are unchanged.'
            : '$e',
      );
    } finally {
      processor = null;
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> restoreText() async {
    final version = page.previousVersion;
    if (busy || version == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Restore previous text?'),
        content: const Text(
          'Restore the saved image and its text together. Current image edits and text will be replaced.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Restore'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    if (!await File(version['path']).exists()) {
      message(
        'The previous image is missing. Your current text has been kept.',
      );
      return;
    }
    if (!mounted) return;
    final before = page.snapshot();
    setState(() {
      busy = true;
      status = 'Restoring previous text';
    });
    try {
      page.restorePreviousVersion();
      await widget.store.save(widget.doc);
      showOriginal = false;
      revision++;
    } catch (e) {
      page.applySnapshot(before);
      page.previousVersion = version;
      message('$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> transform(
    String method, {
    Map<String, dynamic> arguments = const {},
  }) async {
    if (busy ||
        !await confirmReplacement('Change the page image?') ||
        !mounted) {
      return;
    }
    final before = page.snapshot(), previous = page.previousVersion;
    setState(() {
      busy = true;
      status = 'Updating image';
    });
    try {
      final out =
          '${widget.store.directory(widget.doc)}/edit_${page.id}_${DateTime.now().microsecondsSinceEpoch}.jpg';
      final result = await native.invokeMapMethod<String, dynamic>(method, {
        'path': method == 'restore' ? page.source : page.path,
        'out': out,
        ...arguments,
      });
      page.protectText();
      page.path = result!['path'];
      page.width = result['width'];
      page.height = result['height'];
      page.note = result['note'] ?? '';
      page.clearText();
      showOriginal = false;
      await widget.store.save(widget.doc);
      revision++;
    } catch (e) {
      page.applySnapshot(before);
      page.previousVersion = previous;
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(e.toString())));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> crop() async {
    final corners = await Navigator.push<List<List<double>>>(
      context,
      MaterialPageRoute(builder: (_) => CropScreen(page: page)),
    );
    if (corners != null && mounted) {
      await transform('crop', arguments: {'points': corners});
    }
  }

  Future<void> editLine(Map<String, dynamic> line) async {
    var draft = line['text'] as String;
    final result = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Review this line'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Original: ${line['original']}'),
              const SizedBox(height: 12),
              SizedBox(
                height: 220,
                child: InteractiveViewer(
                  maxScale: 8,
                  child: Image.file(File(page.path), fit: BoxFit.contain),
                ),
              ),
              const Text('Pinch to inspect the page.'),
              if (line['digitAlternative'] != null) ...[
                const SizedBox(height: 12),
                Text('Enlarged crop reading: ${line['digitAlternative']}'),
                Text(reviewLabel(line)),
                const Text(
                  'Both readings use the same OCR engine. Check the page image before confirming.',
                ),
              ],
              const SizedBox(height: 16),
              TextFormField(
                initialValue: draft,
                onChanged: (value) => draft = value,
                maxLines: null,
                decoration: const InputDecoration(labelText: 'Corrected text'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, draft),
            child: const Text('Confirm'),
          ),
        ],
      ),
    );
    if (result != null && mounted) {
      final oldText = line['text'], oldReviewed = line['reviewed'];
      line['text'] = result;
      line['reviewed'] = true;
      try {
        await widget.store.save(widget.doc);
      } catch (e) {
        line['text'] = oldText;
        line['reviewed'] = oldReviewed;
        message('Could not save this correction: $e');
      }
      if (mounted) setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Review page'),
          bottom: const TabBar(
            tabs: [
              Tab(text: 'Image'),
              Tab(text: 'Text'),
            ],
          ),
        ),
        body: SafeArea(
          child: busy
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const CircularProgressIndicator(),
                        const SizedBox(height: 24),
                        Text(status, textAlign: TextAlign.center),
                        if (processor != null) ...[
                          const SizedBox(height: 16),
                          OutlinedButton(
                            onPressed: processor!.cancelled
                                ? null
                                : () {
                                    setState(() {
                                      processor!.cancelled = true;
                                      status =
                                          'Stopping after the current step…';
                                    });
                                  },
                            child: const Text('Cancel'),
                          ),
                        ],
                      ],
                    ),
                  ),
                )
              : Column(
                  children: [
                    Expanded(
                      child: TabBarView(
                        children: [
                          Column(
                            children: [
                              Expanded(
                                child: InteractiveViewer(
                                  minScale: .5,
                                  maxScale: 5,
                                  child: Center(
                                    child: Image.file(
                                      File(
                                        showOriginal ? page.source : page.path,
                                      ),
                                      key: ValueKey('${page.path}$revision'),
                                      fit: BoxFit.contain,
                                    ),
                                  ),
                                ),
                              ),
                              Padding(
                                padding: const EdgeInsets.all(16),
                                child: Wrap(
                                  spacing: 12,
                                  runSpacing: 8,
                                  alignment: WrapAlignment.center,
                                  children: [
                                    TextButton.icon(
                                      onPressed: () => setState(
                                        () => showOriginal = !showOriginal,
                                      ),
                                      icon: const Icon(Icons.compare_outlined),
                                      label: Text(
                                        showOriginal
                                            ? 'Show processed'
                                            : 'Compare original',
                                      ),
                                    ),
                                    OutlinedButton.icon(
                                      onPressed: () => transform(
                                        'rotate',
                                        arguments: {'degrees': 90},
                                      ),
                                      icon: const Icon(Icons.rotate_right),
                                      label: const Text('Rotate'),
                                    ),
                                    OutlinedButton.icon(
                                      onPressed: crop,
                                      icon: const Icon(Icons.crop),
                                      label: const Text('Crop corners'),
                                    ),
                                    TextButton(
                                      onPressed: () => transform('enhance'),
                                      child: const Text('Enhance & upscale'),
                                    ),
                                    TextButton(
                                      onPressed: () => transform('restore'),
                                      child: const Text('Auto-align original'),
                                    ),
                                    TextButton(
                                      onPressed: () => transform(
                                        'normalize',
                                        arguments: {'path': page.source},
                                      ),
                                      child: const Text('Reset original'),
                                    ),
                                  ],
                                ),
                              ),
                              const Padding(
                                padding: EdgeInsets.only(bottom: 12),
                                child: Text(
                                  'Review the image, then recognize its text.',
                                ),
                              ),
                            ],
                          ),
                          !page.recognized
                              ? const Center(
                                  child: Padding(
                                    padding: EdgeInsets.all(24),
                                    child: Text(
                                      'Tap Recognize text below to read this page offline. Then tap a line to review or correct it.',
                                      textAlign: TextAlign.center,
                                    ),
                                  ),
                                )
                              : page.lines.isEmpty
                              ? const Center(
                                  child: Text(
                                    'No text detected. Try a sharper photo.',
                                  ),
                                )
                              : ListView.builder(
                                  padding: const EdgeInsets.all(16),
                                  itemCount: page.lines.length,
                                  itemBuilder: (_, index) {
                                    final line = page.lines[index];
                                    return Card(
                                      child: ListTile(
                                        title: Text(line['text']),
                                        subtitle: Text(reviewLabel(line)),
                                        leading: Icon(
                                          needsReview(line)
                                              ? Icons.help_outline
                                              : Icons.check_circle_outline,
                                        ),
                                        trailing: const Icon(
                                          Icons.edit_outlined,
                                        ),
                                        onTap: () => editLine(line),
                                      ),
                                    );
                                  },
                                ),
                        ],
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          if (page.previousVersion != null)
                            TextButton.icon(
                              onPressed: restoreText,
                              icon: const Icon(Icons.restore),
                              label: const Text('Restore previous text'),
                            ),
                          FilledButton.icon(
                            onPressed: recognize,
                            icon: const Icon(Icons.text_snippet_outlined),
                            label: Text(
                              page.recognized
                                  ? 'Recognize again'
                                  : 'Recognize text',
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
        ),
      ),
    ),
  );
}

class CropScreen extends StatefulWidget {
  const CropScreen({super.key, required this.page});
  final ScanPage page;
  @override
  State<CropScreen> createState() => _CropScreenState();
}

class _CropScreenState extends State<CropScreen> {
  final points = <Offset>[
    const Offset(.03, .03),
    const Offset(.97, .03),
    const Offset(.97, .97),
    const Offset(.03, .97),
  ];
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Set four corners'),
      actions: [
        TextButton(
          onPressed: () {
            Navigator.pop(context, points.map((p) => [p.dx, p.dy]).toList());
          },
          child: const Text('Apply'),
        ),
      ],
    ),
    body: SafeArea(
      child: Column(
        children: [
          const Padding(
            padding: EdgeInsets.all(20),
            child: Text(
              'Drag the corners clockwise: top left, top right, bottom right, bottom left.',
            ),
          ),
          Expanded(
            child: Center(
              child: AspectRatio(
                aspectRatio: widget.page.width / widget.page.height,
                child: LayoutBuilder(
                  builder: (_, bounds) => Stack(
                    clipBehavior: Clip.none,
                    children: [
                      Positioned.fill(
                        child: Image.file(
                          File(widget.page.path),
                          fit: BoxFit.fill,
                        ),
                      ),
                      Positioned.fill(
                        child: IgnorePointer(
                          child: CustomPaint(painter: CornerPainter(points)),
                        ),
                      ),
                      for (var i = 0; i < 4; i++)
                        Positioned(
                          left: points[i].dx * bounds.maxWidth - 24,
                          top: points[i].dy * bounds.maxHeight - 24,
                          child: GestureDetector(
                            onPanUpdate: (event) => setState(
                              () => points[i] = Offset(
                                (points[i].dx +
                                        event.delta.dx / bounds.maxWidth)
                                    .clamp(0, 1),
                                (points[i].dy +
                                        event.delta.dy / bounds.maxHeight)
                                    .clamp(0, 1),
                              ),
                            ),
                            child: Semantics(
                              label: 'Crop corner ${i + 1}',
                              child: Container(
                                width: 48,
                                height: 48,
                                alignment: Alignment.center,
                                child: Container(
                                  width: 24,
                                  height: 24,
                                  decoration: BoxDecoration(
                                    color: Theme.of(
                                      context,
                                    ).colorScheme.primary,
                                    border: Border.all(
                                      color: Colors.black,
                                      width: 2,
                                    ),
                                    shape: BoxShape.circle,
                                  ),
                                  child: Center(
                                    child: Text(
                                      '${i + 1}',
                                      style: const TextStyle(
                                        color: Colors.black,
                                        fontSize: 12,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 32),
        ],
      ),
    ),
  );
}

class CornerPainter extends CustomPainter {
  CornerPainter(this.points);
  final List<Offset> points;
  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..moveTo(points[0].dx * size.width, points[0].dy * size.height);
    for (final p in points.skip(1)) {
      path.lineTo(p.dx * size.width, p.dy * size.height);
    }
    path.close();
    canvas.drawPath(
      path,
      Paint()
        ..color = Colors.amber
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(CornerPainter oldDelegate) => true;
}
