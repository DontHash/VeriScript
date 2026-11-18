import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'documents.dart';
import 'processing.dart';
import 'errors.dart';

class PageEditor extends StatefulWidget {
  const PageEditor({
    super.key,
    required this.page,
    required this.store,
    required this.doc,
    this.language = 'ne',
    this.engine = 'mlkit',
    this.autoRotate = true,
    this.checkDigits = true,
  });
  final ScanPage page;
  final DocumentStore store;
  final ScanDocument doc;
  final String language;
  final String engine;
  final bool autoRotate, checkDigits;
  @override
  State<PageEditor> createState() => _PageEditorState();
}

class _PageEditorState extends State<PageEditor> {
  ScanPage get page => widget.page;
  bool busy = false;
  int revision = 0;
  bool showOriginal = false;

  /// Word-by-word review (docs/TECH_UPGRADE_PLAN.md D5).
  bool wordView = false;

  Future<void> editWord(WordRef ref) async {
    final word = ref.word;
    var draft = word['text'] as String? ?? '';
    final result = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Check this word'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              WordCrop(page: page, bbox: word['bbox'] as List?, height: 96),
              const SizedBox(height: 8),
              Text('In the line: ${ref.line['text']}'),
              const SizedBox(height: 16),
              TextFormField(
                initialValue: draft,
                autofocus: true,
                onChanged: (value) => draft = value,
                decoration: const InputDecoration(labelText: 'Word'),
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
    if (result == null || result.trim().isEmpty || !mounted) return;
    final oldText = ref.line['text'], oldWords = ref.line['words'];
    correctWord(ref, result);
    try {
      await widget.store.save(widget.doc);
    } catch (e) {
      ref.line['text'] = oldText;
      ref.line['words'] = oldWords;
      message(
        friendlyError(
          e,
          'Could not save this correction. The previous text is kept.',
        ),
      );
    }
    if (mounted) setState(() {});
  }

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
    final worker = OfflineProcessor(widget.language, engine: widget.engine);
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
            : friendlyError(
                e,
                'Recognition failed. Your previous image and text are unchanged. Try again.',
              ),
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
      message(
        friendlyError(
          e,
          'Could not restore the previous text. Your current text is unchanged.',
        ),
      );
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              friendlyError(
                e,
                'The image could not be updated. Your page is unchanged.',
              ),
            ),
          ),
        );
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
        message(
          friendlyError(
            e,
            'Could not save this correction. The previous text is kept.',
          ),
        );
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
                                    // Less frequent image tools in one
                                    // menu, so the bar fits at large text
                                    // sizes. F1 "Flatten curved page" is
                                    // opt-in per page (UVDoc); Restore
                                    // previous text or Reset original undo it.
                                    PopupMenuButton<(String, Map<String, dynamic>)>(
                                      tooltip: 'More image tools',
                                      onSelected: (v) =>
                                          transform(v.$1, arguments: v.$2),
                                      itemBuilder: (_) => [
                                        const PopupMenuItem(
                                          value: ('enhance', <String, dynamic>{}),
                                          child: Text('Enhance & upscale'),
                                        ),
                                        const PopupMenuItem(
                                          value: ('restore', <String, dynamic>{}),
                                          child: Text('Auto-align original'),
                                        ),
                                        const PopupMenuItem(
                                          value: ('flatten', <String, dynamic>{}),
                                          child: Text('Flatten curved page'),
                                        ),
                                        PopupMenuItem(
                                          value: ('normalize', {'path': page.source}),
                                          child: const Text('Reset original'),
                                        ),
                                      ],
                                      child: const Padding(
                                        padding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                                        child: Row(
                                          mainAxisSize: MainAxisSize.min,
                                          children: [
                                            Icon(Icons.more_horiz),
                                            SizedBox(width: 8),
                                            Text('More'),
                                          ],
                                        ),
                                      ),
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
                              : Column(
                                  children: [
                                    if (page.lines.any(
                                      (l) =>
                                          (l['words'] as List?)?.isNotEmpty ==
                                          true,
                                    ))
                                      Padding(
                                        padding: const EdgeInsets.fromLTRB(
                                          16,
                                          8,
                                          16,
                                          0,
                                        ),
                                        child: SegmentedButton<bool>(
                                          segments: [
                                            const ButtonSegment(
                                              value: false,
                                              label: Text('Lines'),
                                            ),
                                            ButtonSegment(
                                              value: true,
                                              label: Text(
                                                'Words to check (${wordsToCheck(page.lines).length})',
                                              ),
                                            ),
                                          ],
                                          selected: {wordView},
                                          onSelectionChanged: (v) => setState(
                                            () => wordView = v.first,
                                          ),
                                        ),
                                      ),
                                    Expanded(
                                      child: wordView
                                          ? _wordList()
                                          : _lineList(),
                                    ),
                                  ],
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

  Widget _wordList() {
    final words = wordsToCheck(page.lines);
    if (words.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'No words left to check on this page.',
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: words.length,
      itemBuilder: (_, index) {
        final ref = words[index];
        final word = ref.word;
        return Card(
          child: ListTile(
            leading: SizedBox(
              width: 96,
              child: WordCrop(
                page: page,
                bbox: word['bbox'] as List?,
                height: 40,
              ),
            ),
            title: Text(word['text'] as String? ?? ''),
            subtitle: Text(
              RegExp(r'[0-9०-९০-৯]').hasMatch(word['text'] as String? ?? '')
                  ? 'Number · compare with the picture'
                  : 'Low confidence · compare with the picture',
            ),
            trailing: const Icon(Icons.edit_outlined),
            onTap: () => editWord(ref),
          ),
        );
      },
    );
  }

  Widget _lineList() => ListView.builder(
    padding: const EdgeInsets.all(16),
    itemCount: page.lines.length,
    itemBuilder: (_, index) {
      final line = page.lines[index];
      return Card(
        child: ListTile(
          title: Text(line['text']),
          subtitle: Text(reviewLabel(line)),
          leading: Icon(
            needsReview(line) ? Icons.help_outline : Icons.check_circle_outline,
          ),
          trailing: const Icon(Icons.edit_outlined),
          onTap: () => editLine(line),
        ),
      );
    },
  );
}

class CropScreen extends StatefulWidget {
  const CropScreen({super.key, required this.page});
  final ScanPage page;
  @override
  State<CropScreen> createState() => _CropScreenState();
}

/// Four-corner crop. Corners can be dragged, or moved without dragging
/// (WCAG 2.5.7): select a corner, then use the arrow buttons, or use the
/// TalkBack custom actions on each corner ("Move left", …).
class _CropScreenState extends State<CropScreen> {
  static const names = ['top left', 'top right', 'bottom right', 'bottom left'];

  /// One arrow press or TalkBack action moves a corner 1% of the page.
  static const step = .01;

  final points = <Offset>[
    const Offset(.03, .03),
    const Offset(.97, .03),
    const Offset(.97, .97),
    const Offset(.03, .97),
  ];
  int selected = 0;

  String position(int i) =>
      '${(points[i].dx * 100).round()}% across, '
      '${(points[i].dy * 100).round()}% down';

  void nudge(int i, double dx, double dy) {
    setState(() {
      selected = i;
      points[i] = Offset(
        (points[i].dx + dx).clamp(0.0, 1.0),
        (points[i].dy + dy).clamp(0.0, 1.0),
      );
    });
  }

  Widget arrow(IconData icon, String direction, double dx, double dy) =>
      IconButton.outlined(
        tooltip: 'Move ${names[selected]} corner $direction',
        onPressed: () => nudge(selected, dx, dy),
        icon: Icon(icon),
      );

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
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
              padding: EdgeInsets.fromLTRB(20, 16, 20, 8),
              child: Text(
                'Drag the corners clockwise: top left, top right, bottom right, '
                'bottom left. Or pick a corner and use the arrows.',
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
                            excludeFromSemantics: true,
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
                            child: Semantics(
                              label: 'Crop corner ${i + 1}, ${names[i]}',
                              value: position(i),
                              selected: selected == i,
                              customSemanticsActions: {
                                const CustomSemanticsAction(
                                  label: 'Move left',
                                ): () =>
                                    nudge(i, -step, 0),
                                const CustomSemanticsAction(
                                  label: 'Move right',
                                ): () =>
                                    nudge(i, step, 0),
                                const CustomSemanticsAction(
                                  label: 'Move up',
                                ): () =>
                                    nudge(i, 0, -step),
                                const CustomSemanticsAction(
                                  label: 'Move down',
                                ): () =>
                                    nudge(i, 0, step),
                              },
                              child: GestureDetector(
                                onTap: () => setState(() => selected = i),
                                onPanStart: (_) => setState(() => selected = i),
                                onPanUpdate: (event) => nudge(
                                  i,
                                  event.delta.dx / bounds.maxWidth,
                                  event.delta.dy / bounds.maxHeight,
                                ),
                                child: Container(
                                  width: 48,
                                  height: 48,
                                  alignment: Alignment.center,
                                  child: Container(
                                    width: selected == i ? 30 : 26,
                                    height: selected == i ? 30 : 26,
                                    decoration: BoxDecoration(
                                      color: scheme.primary,
                                      border: Border.all(
                                        color: Colors.black,
                                        width: selected == i ? 3 : 2,
                                      ),
                                      shape: BoxShape.circle,
                                    ),
                                    child: Center(
                                      child: ExcludeSemantics(
                                        child: Text(
                                          '${i + 1}',
                                          style: const TextStyle(
                                            color: Colors.black,
                                            fontSize: 14,
                                          ),
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
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
              child: Column(
                children: [
                  SegmentedButton<int>(
                    showSelectedIcon: false,
                    segments: [
                      for (var i = 0; i < 4; i++)
                        ButtonSegment(
                          value: i,
                          label: Text('${i + 1}'),
                          tooltip: 'Select the ${names[i]} corner',
                        ),
                    ],
                    selected: {selected},
                    onSelectionChanged: (value) =>
                        setState(() => selected = value.first),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      arrow(Icons.arrow_back, 'left', -step, 0),
                      const SizedBox(width: 8),
                      arrow(Icons.arrow_upward, 'up', 0, -step),
                      const SizedBox(width: 8),
                      arrow(Icons.arrow_downward, 'down', 0, step),
                      const SizedBox(width: 8),
                      arrow(Icons.arrow_forward, 'right', step, 0),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Semantics(
                    liveRegion: true,
                    child: Text(
                      'Corner ${selected + 1} (${names[selected]}): '
                      '${position(selected)}',
                      textAlign: TextAlign.center,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
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

/// The part of the page picture inside [bbox] (page-image pixels), scaled
/// to [height]: the word as printed, beside what was read (D5).
class WordCrop extends StatelessWidget {
  const WordCrop({
    super.key,
    required this.page,
    required this.bbox,
    this.height = 48,
  });
  final ScanPage page;
  final List? bbox;
  final double height;

  @override
  Widget build(BuildContext context) {
    final b = bbox;
    if (b == null || b.length != 4 || page.width <= 1 || page.height <= 1) {
      return SizedBox(height: height);
    }
    final pad = (b[3] as num).toDouble() * .25;
    final left = ((b[0] as num).toDouble() - pad).clamp(0.0, page.width - 1.0);
    final top = ((b[1] as num).toDouble() - pad).clamp(0.0, page.height - 1.0);
    final w = ((b[2] as num).toDouble() + 2 * pad).clamp(
      1.0,
      page.width - left,
    );
    final h = ((b[3] as num).toDouble() + 2 * pad).clamp(
      1.0,
      page.height - top,
    );
    final pw = page.width.toDouble(), ph = page.height.toDouble();
    return Semantics(
      label: 'Picture of the word on the page',
      image: true,
      child: SizedBox(
        height: height,
        child: FittedBox(
          fit: BoxFit.contain,
          alignment: Alignment.centerLeft,
          child: ClipRect(
            child: Align(
              alignment: Alignment(
                pw - w <= 0 ? 0 : left / (pw - w) * 2 - 1,
                ph - h <= 0 ? 0 : top / (ph - h) * 2 - 1,
              ),
              widthFactor: w / pw,
              heightFactor: h / ph,
              child: Image.file(
                File(page.path),
                width: pw,
                height: ph,
                fit: BoxFit.fill,
                cacheWidth: page.width > 2400 ? 2400 : null,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
