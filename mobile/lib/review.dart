import 'dart:convert';
import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:image_picker/image_picker.dart';
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'background.dart';
import 'documents.dart';
import 'exports.dart';
import 'processing.dart';
import 'capture.dart';
import 'editor.dart';
import 'copy.dart';
import 'errors.dart';

class ReviewScreen extends StatefulWidget {
  const ReviewScreen({
    super.key,
    required this.doc,
    required this.store,
    required this.settings,
    this.initial,
  });
  final ScanDocument doc;
  final DocumentStore store;
  final SharedPreferences settings;
  final String? initial;
  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  ScanDocument get doc => widget.doc;
  bool busy = false, cancelled = false;
  String status = '';
  double? fraction;
  OfflineProcessor? processor;
  bool grid = true;
  @override
  void initState() {
    super.initState();
    grid = widget.settings.getBool('reviewGrid') ?? true;
    native.setMethodCallHandler((call) async {
      if (call.method == 'progress' && mounted && busy) {
        setState(
          () => fraction =
              (call.arguments['done'] as num) /
              (call.arguments['total'] as num),
        );
      }
    });
    if (widget.initial != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (widget.initial == 'camera') {
          capture();
        } else if (widget.initial == 'video') {
          video();
        } else {
          importMenu();
        }
      });
    }
  }

  @override
  void dispose() {
    native.setMethodCallHandler(null);
    super.dispose();
  }

  void message(String value) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(value)));
    }
  }

  void checkCancelled() {
    if (cancelled) throw StateError('Operation cancelled');
  }

  Future<void> work(String label, Future<void> Function() task) async {
    if (busy) return;
    setState(() {
      busy = true;
      cancelled = false;
      status = label;
      fraction = null;
    });
    // Long work keeps running (with a progress notification) if the user
    // switches apps; short work never shows one.
    final notice = ProcessingNotice(doc.title, () => (status, fraction))
      ..begin();
    try {
      await task();
    } catch (e) {
      message(
        cancelled
            ? 'Stopped. Previously saved draft pages are kept.'
            : friendlyError(e, 'That did not finish. Try again.'),
      );
    } finally {
      processor = null;
      await notice.end();
      try {
        await widget.store.save(doc);
      } catch (e) {
        message(
          friendlyError(
            e,
            'The draft could not be saved. Check free storage, then try again.',
          ),
        );
      }
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> capture() async {
    final first = doc.pages.length;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => CaptureScreen(
          count: doc.pages.length,
          onPhoto: (path) async {
            if (doc.pages.length >= 150) {
              throw StateError('150-page limit reached.');
            }
            final page = await widget.store.importImage(
              doc,
              path,
              align: false,
              enhance: false,
            );
            return () => widget.store.removePage(doc, page);
          },
        ),
      ),
    );
    if (!mounted) return;
    if ((widget.settings.getBool('align') ?? true) ||
        (widget.settings.getBool('enhance') ?? true)) {
      await work('Aligning captured pages', () async {
        final pages = doc.pages.skip(first).toList();
        for (var i = 0; i < pages.length; i++) {
          checkCancelled();
          final p = pages[i];
          var info = widget.settings.getBool('align') ?? true
              ? await native.invokeMapMethod<String, dynamic>('restore', {
                  'path': p.source,
                  'out': '${widget.store.directory(doc)}/aligned_${p.id}.jpg',
                })
              : {
                  'path': p.source,
                  'width': p.width,
                  'height': p.height,
                  'note': p.note,
                };
          if (widget.settings.getBool('enhance') ?? true) {
            info = await native.invokeMapMethod<String, dynamic>('enhance', {
              'path': info!['path'],
              'out': '${widget.store.directory(doc)}/enhanced_${p.id}.jpg',
            });
          }
          p.path = info!['path'];
          p.width = info['width'];
          p.height = info['height'];
          p.note = info['note'];
          await widget.store.save(doc);
          setState(() => fraction = (i + 1) / pages.length);
        }
      });
    }
    setState(() {});
  }

  Future<void> importMenu() async {
    final type = await showModalBottomSheet<String>(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.collections_outlined),
              title: const Text('Choose multiple images'),
              onTap: () => Navigator.pop(context, 'images'),
            ),
            ListTile(
              leading: const Icon(Icons.picture_as_pdf_outlined),
              title: const Text('Import a PDF · up to 150 pages'),
              onTap: () => Navigator.pop(context, 'pdf'),
            ),
          ],
        ),
      ),
    );
    if (type == 'images') {
      final images = await ImagePicker().pickMultiImage();
      if (images.isEmpty || !mounted) return;
      await work('Importing images', () async {
        if (doc.pages.length + images.length > 150) {
          throw StateError(
            'A document is limited to 150 pages. Select fewer images.',
          );
        }
        for (var i = 0; i < images.length; i++) {
          checkCancelled();
          await widget.store.importImage(
            doc,
            images[i].path,
            align: widget.settings.getBool('align') ?? true,
            enhance: widget.settings.getBool('enhance') ?? true,
          );
          setState(() => fraction = (i + 1) / images.length);
        }
      });
    } else if (type == 'pdf') {
      final picked = await FilePicker.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['pdf'],
      );
      final path = picked.isEmpty ? null : picked.single.path;
      if (path == null || !mounted) return;
      await work('Importing PDF pages', () async {
        final info = await native.invokeMapMethod<String, dynamic>('pdfInfo', {
          'path': path,
        });
        final count = info!['pages'] as int;
        if (count + doc.pages.length > 150) {
          throw StateError(
            'Import would exceed 150 pages. Split the PDF first.',
          );
        }
        for (var i = 0; i < count; i++) {
          checkCancelled();
          final out =
              '${widget.store.directory(doc)}/pdf_${DateTime.now().microsecondsSinceEpoch}.jpg';
          await native.invokeMethod('pdfPage', {
            'path': path,
            'out': out,
            'index': i,
          });
          await widget.store.importImage(
            doc,
            out,
            align: false,
            enhance: widget.settings.getBool('enhance') ?? true,
          );
          await File(out).delete();
          setState(() => fraction = (i + 1) / count);
        }
      });
    }
  }

  Future<void> video() async {
    final options = await showModalBottomSheet<(String, String, bool)>(
      context: context,
      builder: (_) => const VideoOptionsSheet(),
    );
    if (options == null || !mounted) return;
    String? path;
    if (options.$1 == 'record') {
      path = await Navigator.of(context).push<String>(
        MaterialPageRoute(
          builder: (_) => const CaptureScreen(recordMode: true),
        ),
      );
    } else {
      final picked = await FilePicker.pickFiles(type: FileType.video);
      path = picked.isEmpty ? null : picked.single.path;
    }
    if (path == null || !mounted) return;
    await work('Finding steady book pages', () async {
      final dir = widget.store.directory(doc);
      final source = await File(
        path!,
      ).copy('$dir/source_video_${DateTime.now().microsecondsSinceEpoch}.mp4');
      final result = await native.invokeMapMethod<String, dynamic>('video', {
        'path': source.path,
        'out': '$dir/video_${DateTime.now().microsecondsSinceEpoch}',
        'layout': options.$2,
        'cleanFingers': options.$3,
      });
      doc.warnings = [
        ...doc.warnings,
        ...List<String>.from(result!['warnings']),
      ];
      final pages = result['pages'] as List;
      if (pages.length + doc.pages.length > 150) {
        throw StateError(
          'This batch exceeds 150 pages. Create a separate document.',
        );
      }
      for (var i = 0; i < pages.length; i++) {
        checkCancelled();
        final page = await widget.store.importImage(
          doc,
          pages[i]['path'],
          align: false,
          enhance: widget.settings.getBool('enhance') ?? true,
        );
        page.note =
            '${pages[i]['side']} · ${(pages[i]['timestamp'] as num).toStringAsFixed(2)} s';
        await widget.store.save(doc);
        setState(() {
          status = 'Saving book pages';
          fraction = (i + 1) / pages.length;
        });
      }
    });
  }

  Future<void> recognize() async {
    processor = OfflineProcessor(
      widget.settings.getString('language') ?? 'ne',
      engine: widget.settings.getString('ocrEngine') ?? 'mlkit',
    );
    final pages = doc.selected.where((p) => !p.recognized).toList();
    for (var i = 0; i < pages.length; i++) {
      checkCancelled();
      setState(() => status = 'Recognizing page ${i + 1} of ${pages.length}');
      setState(() => fraction = i / pages.length);
      await processor!.recognize(
        pages[i],
        autoRotate: widget.settings.getBool('rotate') ?? true,
        checkDigits: widget.settings.getBool('digits') ?? true,
        onProgress: (stage) {
          if (mounted) {
            setState(
              () => status = 'Page ${i + 1} of ${pages.length} · $stage',
            );
          }
        },
      );
      await widget.store.save(doc);
      setState(() => fraction = (i + 1) / pages.length);
    }
  }

  Future<void> share(String path) async {
    final box = context.findRenderObject() as RenderBox?;
    await SharePlus.instance.share(
      ShareParams(
        files: [XFile(path)],
        sharePositionOrigin: box == null
            ? null
            : box.localToGlobal(Offset.zero) & box.size,
      ),
    );
  }

  Future<void> export() async {
    if (doc.selected.isEmpty) {
      message('Select at least one page.');
      return;
    }
    var smallPdf = widget.settings.getBool('smallPdf') ?? false;
    var protect = false;
    final kind = await showModalBottomSheet<ExportKind>(
      context: context,
      isScrollControlled: true,
      builder: (_) => SafeArea(
        child: SingleChildScrollView(
          child: StatefulBuilder(
            builder: (context, setSheet) => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Padding(
                  padding: EdgeInsets.all(24),
                  child: Text(
                    'Choose an export',
                    style: TextStyle(fontSize: 24),
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.fromLTRB(24, 0, 24, 16),
                  child: Text(
                    'Text exports recognize unread selected pages first. Review names and numbers before sharing.',
                  ),
                ),
                SwitchListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 24),
                  title: const Text('Smaller PDF for sharing'),
                  subtitle: const Text(
                    'Page pictures at 150 DPI for messages and email. The searchable text stays the same; check small print before sending.',
                  ),
                  value: smallPdf,
                  onChanged: (v) {
                    setSheet(() => smallPdf = v);
                    widget.settings.setBool('smallPdf', v);
                  },
                ),
                SwitchListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 24),
                  title: const Text('Protect PDFs with a password'),
                  subtitle: const Text(
                    'The PDF opens only with the password. Nobody can recover a lost password.',
                  ),
                  value: protect,
                  onChanged: (v) => setSheet(() => protect = v),
                ),
                ...ExportKind.values.map(
                  (kind) => ListTile(
                    title: Text(kind.label),
                    subtitle: Text(kind.guidance),
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 24,
                      vertical: 8,
                    ),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => Navigator.pop(context, kind),
                  ),
                ),
                const SizedBox(height: 16),
              ],
            ),
          ),
        ),
      ),
    );
    if (kind == null || !mounted) return;
    String? password;
    if (protect &&
        (kind == ExportKind.imagePdf || kind == ExportKind.searchablePdf)) {
      password = await askPdfPassword(context);
      if (password == null || !mounted) return;
    }
    File? file;
    await work('Preparing export', () async {
      if (kind.needsText) await recognize();
      checkCancelled();
      setState(() => status = 'Writing ${kind.extension.toUpperCase()}');
      file = await exportDocument(
        widget.store,
        doc,
        kind,
        progress: (done, total) => setState(() => fraction = done / total),
        cancelled: () => cancelled,
        smallPdf: smallPdf,
        password: password,
      );
    });
    final done = file;
    if (done != null && mounted) await deliver(done.path);
  }

  /// E5: an export goes to another app (Share) or to a place the user picks
  /// (Save to…, through Android's own file picker). The file stays in
  /// Saved exports either way.
  Future<void> deliver(String path) async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              title: const Text('Export ready', style: TextStyle(fontSize: 24)),
              subtitle: Text(path.split('/').last),
            ),
            ListTile(
              leading: const Icon(Icons.ios_share),
              title: const Text('Share'),
              subtitle: const Text(
                'Send to another app, such as email or messages.',
              ),
              onTap: () => Navigator.pop(context, 'share'),
            ),
            ListTile(
              leading: const Icon(Icons.save_alt),
              title: const Text('Save to…'),
              subtitle: const Text(
                'Choose a folder on this phone, a memory card or a USB drive.',
              ),
              onTap: () => Navigator.pop(context, 'save'),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (!mounted || choice == null) return;
    if (choice == 'share') {
      await share(path);
    } else {
      try {
        if (await saveExportAs(path)) message('Saved ${path.split('/').last}.');
      } catch (e) {
        message(friendlyError(e, 'The file could not be saved there.'));
      }
    }
  }

  Future<void> rename() async {
    final value = await showDialog<String>(
      context: context,
      builder: (_) => NameDialog(
        title: 'Document name',
        initial: doc.title,
        action: 'Save',
      ),
    );
    if (value != null && value.trim().isNotEmpty) {
      doc.title = value.trim();
      await widget.store.save(doc);
      setState(() {});
    }
  }

  /// E5 split: the selected pages become a new document.
  Future<void> moveSelected() async {
    final pages = doc.selected.toList();
    if (pages.isEmpty || pages.length == doc.pages.length) {
      message('Select the pages to move. At least one page must stay.');
      return;
    }
    final title = await showDialog<String>(
      context: context,
      builder: (_) => NameDialog(
        title: 'Move ${countLabel(pages.length, 'page')} to a new document',
        initial: '${doc.title} (2)',
        action: 'Move',
        label: 'New document name',
      ),
    );
    if (title == null || title.trim().isEmpty || !mounted) return;
    await work('Moving pages', () async {
      final created = await widget.store.movePagesToNew(
        doc,
        pages,
        title.trim(),
        progress: (done, total) => setState(() => fraction = done / total),
      );
      message(
        'Moved ${countLabel(pages.length, 'page')} to “${created.title}”.',
      );
    });
  }

  /// E5 combine: copies of another document's pages are added at the end.
  Future<void> addFromDocument() async {
    final others = (await widget.store.list())
        .where((d) => d.id != doc.id)
        .toList();
    if (!mounted) return;
    if (others.isEmpty) {
      message('There is no other document to add pages from.');
      return;
    }
    final source = await showModalBottomSheet<ScanDocument>(
      context: context,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const ListTile(
              title: Text('Add pages from', style: TextStyle(fontSize: 24)),
              subtitle: Text(
                'Its pages are copied to the end of this document. The other document stays as it is.',
              ),
            ),
            ...others.map(
              (other) => ListTile(
                title: Text(other.title),
                subtitle: Text(countLabel(other.pages.length, 'page')),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.pop(context, other),
              ),
            ),
          ],
        ),
      ),
    );
    if (source == null || !mounted) return;
    await work('Adding pages', () async {
      await widget.store.copyPages(
        source,
        source.pages,
        doc,
        progress: (done, total) => setState(() => fraction = done / total),
      );
      message(
        'Added ${countLabel(source.pages.length, 'page')} from “${source.title}”.',
      );
    });
  }

  Future<void> showExports() async {
    await showModalBottomSheet<void>(
      context: context,
      builder: (_) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const ListTile(
              title: Text('Saved exports', style: TextStyle(fontSize: 24)),
            ),
            if (doc.exports.isEmpty)
              const ListTile(title: Text('No exports yet.')),
            ...doc.exports.reversed.map(
              (path) => ListTile(
                title: Text(path.split('/').last),
                trailing: const Icon(Icons.chevron_right),
                onTap: () async {
                  Navigator.pop(context);
                  if (await File(path).exists()) {
                    await deliver(path);
                  } else {
                    message(
                      'This export is missing. Export again from the saved pages.',
                    );
                  }
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> save() async {
    await widget.store.save(doc);
    if (mounted) setState(() {});
  }

  void layout(bool value) {
    setState(() => grid = value);
    unawaited(widget.settings.setBool('reviewGrid', value));
  }

  void movePage(int index, int delta) {
    doc.pages.insert(index + delta, doc.pages.removeAt(index));
    save();
  }

  Future<void> openPage(ScanPage page) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PageEditor(
          page: page,
          store: widget.store,
          doc: doc,
          language: widget.settings.getString('language') ?? 'ne',
          engine: widget.settings.getString('ocrEngine') ?? 'mlkit',
          autoRotate: widget.settings.getBool('rotate') ?? true,
          checkDigits: widget.settings.getBool('digits') ?? true,
        ),
      ),
    );
    if (mounted) setState(() {});
  }

  String pageStatus(ScanPage page) {
    if (!page.included) return 'Excluded from export';
    if (!page.recognized) return 'Ready to recognize';
    final count = page.lines.where(needsReview).length;
    if (page.lines.isEmpty) return 'No text detected';
    return count == 0 ? 'Text ready' : '${countLabel(count, 'line')} to review';
  }

  Widget pageImage(ScanPage page) => ColoredBox(
    color: const Color(0xfffcfaf4),
    child: Image.file(
      File(page.path),
      fit: BoxFit.contain,
      cacheWidth: grid ? 360 : 240,
      width: double.infinity,
      height: double.infinity,
      errorBuilder: (_, _, _) => const Center(
        child: Icon(Icons.broken_image_outlined, color: Color(0xff120e08)),
      ),
    ),
  );

  Widget pageCard(int index, {required bool compact}) {
    final page = doc.pages[index];
    final scheme = Theme.of(context).colorScheme;
    final caption = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Page ${index + 1}',
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        Text(
          pageStatus(page),
          style: TextStyle(color: scheme.onSurfaceVariant),
        ),
      ],
    );
    // One node for TalkBack: "Edit page 3, <status>" instead of three.
    final preview = Semantics(
      button: true,
      label: 'Edit page ${index + 1}, ${pageStatus(page)}',
      onTap: () => openPage(page),
      excludeSemantics: true,
      child: InkWell(
        key: ValueKey('preview-${page.id}'),
        onTap: () => openPage(page),
        child: compact
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.all(8),
                      child: pageImage(page),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    child: caption,
                  ),
                ],
              )
            : Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    SizedBox(width: 104, height: 144, child: pageImage(page)),
                    const SizedBox(width: 16),
                    Expanded(child: caption),
                  ],
                ),
              ),
      ),
    );
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: page.included ? scheme.primary : scheme.outlineVariant,
          width: page.included ? 2 : 1,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          if (compact) Expanded(child: preview) else preview,
          Row(
            mainAxisAlignment: compact
                ? MainAxisAlignment.spaceEvenly
                : MainAxisAlignment.end,
            children: [
              Semantics(
                label: 'Include page ${index + 1} in exports',
                child: SizedBox(
                  width: 48,
                  height: 48,
                  child: Checkbox(
                    value: page.included,
                    onChanged: (v) {
                      page.included = v!;
                      save();
                    },
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Move page ${index + 1} up',
                onPressed: index == 0 ? null : () => movePage(index, -1),
                icon: const Icon(Icons.arrow_upward),
              ),
              IconButton(
                tooltip: 'Move page ${index + 1} down',
                onPressed: index == doc.pages.length - 1
                    ? null
                    : () => movePage(index, 1),
                icon: const Icon(Icons.arrow_downward),
              ),
              if (!compact)
                ReorderableDragStartListener(
                  index: index,
                  child: const SizedBox(
                    width: 48,
                    height: 48,
                    child: Icon(Icons.drag_handle),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget captureNotes() {
    final notes = <String, List<int>>{};
    for (var i = 0; i < doc.pages.length; i++) {
      if (doc.pages[i].note.isNotEmpty) {
        (notes[doc.pages[i].note] ??= []).add(i + 1);
      }
    }
    if (doc.warnings.isEmpty && notes.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: TextButton.icon(
        icon: const Icon(Icons.info_outline),
        label: const Text('Capture details'),
        onPressed: () => showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          builder: (_) => SafeArea(
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  ListTile(
                    title: const Text('Capture details'),
                    trailing: IconButton(
                      tooltip: 'Close capture details',
                      icon: const Icon(Icons.close),
                      onPressed: () => Navigator.pop(context),
                    ),
                  ),
                  ...doc.warnings.toSet().map((w) => ListTile(title: Text(w))),
                  ...notes.entries.map(
                    (entry) => ListTile(
                      title: Text(entry.key),
                      subtitle: Text(
                        '${entry.value.length == 1 ? 'Page' : 'Pages'} ${entry.value.join(', ')}',
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget reviewHeader() => Column(
    mainAxisSize: MainAxisSize.min,
    children: [
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Row(
          children: [
            Expanded(
              child: Text(
                '${doc.selected.length} selected / ${countLabel(doc.pages.length, 'page')}',
              ),
            ),
            IconButton(
              tooltip: 'Grid view',
              isSelected: grid,
              onPressed: () => layout(true),
              icon: const Icon(Icons.grid_view_outlined),
              selectedIcon: const Icon(Icons.grid_view),
            ),
            IconButton(
              tooltip: 'List view',
              isSelected: !grid,
              onPressed: () => layout(false),
              icon: const Icon(Icons.view_list_outlined),
              selectedIcon: const Icon(Icons.view_list),
            ),
            PopupMenuButton<String>(
              tooltip: 'Document actions',
              onSelected: (value) {
                if (value == 'ocr') {
                  work('Recognizing text', recognize);
                } else if (value == 'exports') {
                  showExports();
                } else if (value == 'move') {
                  moveSelected();
                } else if (value == 'add') {
                  addFromDocument();
                } else if (value == 'select') {
                  for (final p in doc.pages) {
                    p.included = true;
                  }
                  save();
                }
              },
              itemBuilder: (_) => const [
                PopupMenuItem(
                  value: 'ocr',
                  child: Text('Recognize selected pages'),
                ),
                PopupMenuItem(value: 'select', child: Text('Select all pages')),
                PopupMenuItem(value: 'exports', child: Text('Saved exports')),
                PopupMenuItem(
                  value: 'move',
                  child: Text('Move selected pages to a new document'),
                ),
                PopupMenuItem(
                  value: 'add',
                  child: Text('Add pages from another document'),
                ),
              ],
            ),
          ],
        ),
      ),
      if (doc.selected.any((p) => !p.recognized))
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: () => work('Recognizing text', recognize),
              icon: const Icon(Icons.text_snippet_outlined),
              label: Text(
                'Recognize ${countLabel(doc.selected.where((p) => !p.recognized).length, 'unread page')}',
              ),
            ),
          ),
        ),
      ...doc.warnings.toSet().map(
        (warning) => Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.warning_amber,
                color: Theme.of(context).colorScheme.error,
              ),
              const SizedBox(width: 8),
              Expanded(child: Text(warning)),
            ],
          ),
        ),
      ),
      captureNotes(),
      const Padding(
        padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: Text(
          'Tap a preview to edit. Uncheck duplicates. Use arrows to reorder.',
        ),
      ),
    ],
  );
  Widget reviewFooter() => Padding(
    padding: const EdgeInsets.all(16),
    child: Column(
      children: [
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: capture,
                icon: const Icon(Icons.camera_alt_outlined),
                label: const Text('Add photos'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: importMenu,
                icon: const Icon(Icons.add),
                label: const Text('Import'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: doc.selected.isEmpty ? null : export,
            icon: const Icon(Icons.ios_share),
            label: const Text('Export selected pages'),
          ),
        ),
      ],
    ),
  );

  Widget pageList({required bool scrollFooter}) {
    if (!grid && doc.pages.isNotEmpty) {
      return ReorderableListView.builder(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        header: reviewHeader(),
        footer: scrollFooter ? reviewFooter() : null,
        buildDefaultDragHandles: false,
        itemCount: doc.pages.length,
        onReorderItem: (oldIndex, newIndex) {
          doc.pages.insert(newIndex, doc.pages.removeAt(oldIndex));
          save();
        },
        itemBuilder: (_, index) => Padding(
          key: ValueKey(doc.pages[index].id),
          padding: const EdgeInsets.only(bottom: 16),
          child: pageCard(index, compact: false),
        ),
      );
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final scale = MediaQuery.textScalerOf(context).scale(16) / 16;
        final columns = scale > 1.3
            ? 1
            : ((constraints.maxWidth - 32) / 160).floor().clamp(1, 3);
        return CustomScrollView(
          slivers: [
            SliverToBoxAdapter(child: reviewHeader()),
            if (doc.pages.isEmpty)
              const SliverToBoxAdapter(
                child: Padding(
                  padding: EdgeInsets.all(32),
                  child: Text(
                    'Add your pages first.\nReview, reorder, then export.',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 22),
                  ),
                ),
              )
            else
              SliverPadding(
                padding: const EdgeInsets.all(16),
                sliver: SliverGrid.builder(
                  gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: columns,
                    crossAxisSpacing: 16,
                    mainAxisSpacing: 16,
                    mainAxisExtent: 248 + 40 * scale,
                  ),
                  itemCount: doc.pages.length,
                  itemBuilder: (_, index) => pageCard(index, compact: true),
                ),
              ),
            if (scrollFooter) SliverToBoxAdapter(child: reviewFooter()),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: Scaffold(
      appBar: AppBar(
        title: Text(doc.title),
        actions: [
          IconButton(
            tooltip: 'Rename document',
            onPressed: busy ? null : rename,
            icon: const Icon(Icons.edit_outlined),
          ),
        ],
      ),
      body: SafeArea(
        child: busy
            ? Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(32),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      CircularProgressIndicator(value: fraction),
                      const SizedBox(height: 24),
                      Text(
                        status,
                        textAlign: TextAlign.center,
                        style: const TextStyle(fontSize: 22),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Keep VeriScript open while processing.\nCompleted pages are saved as we go.',
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 24),
                      OutlinedButton(
                        onPressed: cancelled
                            ? null
                            : () {
                                setState(() => cancelled = true);
                                processor?.cancelled = true;
                                unawaited(native.invokeMethod('cancel'));
                              },
                        child: Text(cancelled ? 'Stopping…' : 'Cancel'),
                      ),
                    ],
                  ),
                ),
              )
            : LayoutBuilder(
                builder: (context, constraints) {
                  final scale = MediaQuery.textScalerOf(context).scale(16) / 16;
                  final scrollFooter =
                      scale > 1.6 || constraints.maxHeight < 450;
                  return Column(
                    children: [
                      Expanded(child: pageList(scrollFooter: scrollFooter)),
                      if (!scrollFooter) reviewFooter(),
                    ],
                  );
                },
              ),
      ),
    ),
  );
}

/// A one-field name dialog that owns its text controller, so the controller
/// is disposed only after the dialog (and its closing animation) is gone.
class NameDialog extends StatefulWidget {
  const NameDialog({
    super.key,
    required this.title,
    required this.initial,
    required this.action,
    this.label,
  });
  final String title, initial, action;
  final String? label;

  @override
  State<NameDialog> createState() => _NameDialogState();
}

class _NameDialogState extends State<NameDialog> {
  late final controller = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.title),
    content: TextField(
      controller: controller,
      maxLength: 80,
      autofocus: true,
      decoration: widget.label == null
          ? null
          : InputDecoration(labelText: widget.label),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      FilledButton(
        onPressed: () => Navigator.pop(context, controller.text),
        child: Text(widget.action),
      ),
    ],
  );
}

/// E5: asks for a PDF password twice. Returns null when cancelled.
Future<String?> askPdfPassword(BuildContext context) => showDialog<String>(
  context: context,
  builder: (_) => const _PasswordDialog(),
);

class _PasswordDialog extends StatefulWidget {
  const _PasswordDialog();
  @override
  State<_PasswordDialog> createState() => _PasswordDialogState();
}

class _PasswordDialogState extends State<_PasswordDialog> {
  final first = TextEditingController(), second = TextEditingController();
  String? error;

  @override
  void dispose() {
    first.dispose();
    second.dispose();
    super.dispose();
  }

  void submit() {
    final value = first.text;
    setState(() {
      error = value.length < 6
          ? 'Use at least 6 characters.'
          : utf8.encode(value).length > 127
          ? 'That password is too long.'
          : value != second.text
          ? 'The two passwords differ.'
          : null;
    });
    if (error == null) Navigator.pop(context, value);
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('PDF password'),
    content: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text(
          'Anyone opening the PDF needs this password. Write it down: '
          'nobody can recover it, including VeriScript.',
        ),
        const SizedBox(height: 12),
        TextField(
          controller: first,
          obscureText: true,
          autofocus: true,
          autofillHints: const [AutofillHints.newPassword],
          decoration: const InputDecoration(labelText: 'Password'),
        ),
        TextField(
          controller: second,
          obscureText: true,
          autofillHints: const [AutofillHints.newPassword],
          decoration: InputDecoration(labelText: 'Password again', errorText: error),
          onSubmitted: (_) => submit(),
        ),
      ],
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      FilledButton(onPressed: submit, child: const Text('Protect PDF')),
    ],
  );
}
