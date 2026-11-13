import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'documents.dart';
import 'review.dart';
import 'copy.dart';
import 'selection.dart';
import 'scan/scan_diagnostics_screen.dart';
import 'errors.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    VeriScriptApp(
      settings: await SharedPreferences.getInstance(),
      store: await DocumentStore.open(),
    ),
  );
}

ThemeData studioTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final background = Color(dark ? 0xff11151b : 0xfff4f0e6);
  final surface = Color(dark ? 0xff1d2530 : 0xfffcfaf4);
  final ink = Color(dark ? 0xfff4f1e8 : 0xff120e08);
  final amber = Color(dark ? 0xfff2b544 : 0xffe8a200);
  final generated = ColorScheme.fromSeed(
    seedColor: amber,
    brightness: brightness,
  );
  final scheme = generated.copyWith(
    surface: surface,
    primary: amber,
    onPrimary: Color(dark ? 0xff11151b : 0xff120e08),
    onSurface: ink,
    surfaceContainerHighest: Color(dark ? 0xff283341 : 0xffe5dfd1),
    onSurfaceVariant: dark
        ? const Color(0xffa6b2c3)
        : generated.onSurfaceVariant,
    surfaceDim: dark ? background : generated.surfaceDim,
    surfaceBright: dark ? const Color(0xff303c4b) : generated.surfaceBright,
    surfaceContainerLowest: dark
        ? background
        : generated.surfaceContainerLowest,
    surfaceContainerLow: dark
        ? const Color(0xff18202a)
        : generated.surfaceContainerLow,
    surfaceContainer: dark ? surface : generated.surfaceContainer,
    surfaceContainerHigh: dark
        ? const Color(0xff242e3b)
        : generated.surfaceContainerHigh,
    outline: dark ? const Color(0xff78879a) : generated.outline,
    outlineVariant: dark ? const Color(0xff3e4c5e) : generated.outlineVariant,
    primaryContainer: dark
        ? const Color(0xff3f321a)
        : generated.primaryContainer,
    onPrimaryContainer: dark ? amber : generated.onPrimaryContainer,
    secondary: dark ? const Color(0xffa6b2c3) : generated.secondary,
    secondaryContainer: dark
        ? const Color(0xff283341)
        : generated.secondaryContainer,
    onSecondaryContainer: dark ? ink : generated.onSecondaryContainer,
  );
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(12));
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    fontFamily: 'Mukta',
    textTheme: const TextTheme(
      displayLarge: TextStyle(
        fontFamily: 'Instrument Serif',
        fontFamilyFallback: ['Mukta'],
        fontSize: 38,
        height: 1.15,
      ),
      displayMedium: TextStyle(
        fontFamily: 'Instrument Serif',
        fontFamilyFallback: ['Mukta'],
        fontSize: 30,
      ),
    ),
    colorScheme: scheme,
    focusColor: amber.withValues(alpha: 0.2),
    scaffoldBackgroundColor: background,
    appBarTheme: AppBarTheme(
      backgroundColor: background,
      foregroundColor: ink,
      scrolledUnderElevation: 0,
    ),
    cardTheme: CardThemeData(
      color: surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: shape,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(48, 52),
        shape: shape,
      ),
    ),
    // Text buttons sit on the page background, where bright amber is only
    // 1.9:1 in Paper & Ink. Use the deep amber there (5.5:1); Night Studio's
    // amber already reads at > 9:1 on its dark background.
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: dark ? amber : const Color(0xff7d5a00),
        minimumSize: const Size(48, 48),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 48),
        foregroundColor: ink,
        shape: shape,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: ButtonStyle(
        minimumSize: const WidgetStatePropertyAll(Size(48, 48)),
        foregroundColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.disabled)) return null;
          return states.contains(WidgetState.selected)
              ? scheme.onPrimary
              : scheme.onSurfaceVariant;
        }),
        backgroundColor: WidgetStateProperty.resolveWith(
          (states) =>
              states.contains(WidgetState.selected) &&
                  !states.contains(WidgetState.disabled)
              ? amber
              : null,
        ),
      ),
    ),
    chipTheme: ChipThemeData(
      selectedColor: amber,
      checkmarkColor: scheme.onPrimary,
      labelStyle: TextStyle(
        color: WidgetStateColor.resolveWith(
          (states) => states.contains(WidgetState.disabled)
              ? ink.withValues(alpha: 0.38)
              : states.contains(WidgetState.selected)
              ? scheme.onPrimary
              : ink,
        ),
      ),
    ),
    tabBarTheme: TabBarThemeData(
      indicatorColor: amber,
      labelColor: ink,
      unselectedLabelColor: scheme.onSurfaceVariant,
      labelStyle: const TextStyle(
        fontFamily: 'Mukta',
        fontWeight: FontWeight.w600,
      ),
      unselectedLabelStyle: const TextStyle(fontFamily: 'Mukta'),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: surface,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: dark ? surface : null,
      indicatorColor: amber,
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          color: states.contains(WidgetState.selected)
              ? scheme.onPrimary
              : scheme.onSurfaceVariant,
        ),
      ),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontFamily: 'Mukta',
          fontSize: 14,
          color: states.contains(WidgetState.selected)
              ? ink
              : scheme.onSurfaceVariant,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w600
              : FontWeight.w400,
        ),
      ),
    ),
  );
}

class VeriScriptApp extends StatefulWidget {
  const VeriScriptApp({super.key, required this.settings, required this.store});
  final SharedPreferences settings;
  final DocumentStore store;
  @override
  State<VeriScriptApp> createState() => _VeriScriptAppState();
}

class _VeriScriptAppState extends State<VeriScriptApp> {
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'VeriScript',
    debugShowCheckedModeBanner: false,
    theme: studioTheme(Brightness.light),
    darkTheme: studioTheme(Brightness.dark),
    themeMode: ThemeMode.values[widget.settings.getInt('theme') ?? 0],
    home: LibraryScreen(
      store: widget.store,
      settings: widget.settings,
      onAppearance: () => setState(() {}),
    ),
  );
}

class LibraryScreen extends StatefulWidget {
  const LibraryScreen({
    super.key,
    required this.store,
    required this.settings,
    required this.onAppearance,
  });
  final DocumentStore store;
  final SharedPreferences settings;
  final VoidCallback onAppearance;
  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  List<ScanDocument> documents = [];
  int tab = 0;
  String? error;
  String query = '';
  String? folder;
  bool managing = false;
  final searchController = TextEditingController();
  @override
  void dispose() {
    searchController.dispose();
    super.dispose();
  }

  List<ScanDocument> get visibleDocuments => documents
      .where(
        (doc) =>
            (tab == 0 ||
            (doc.matches(query) && (folder == null || doc.folder == folder))),
      )
      .toList();
  @override
  void initState() {
    super.initState();
    unawaited(reload());
  }

  Future<void> reload() async {
    try {
      final docs = await widget.store.list();
      if (mounted) {
        setState(() {
          documents = docs;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(
          () => error = friendlyError(
            e,
            'Your documents could not be loaded. Close and reopen the app.',
          ),
        );
      }
    }
  }

  Future<void> open(ScanDocument doc, {String? initial}) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ReviewScreen(
          doc: doc,
          store: widget.store,
          settings: widget.settings,
          initial: initial,
        ),
      ),
    );
    await reload();
  }

  Future<void> create(String action) async {
    final doc = await widget.store.create(
      action == 'video' ? 'Captured book' : 'New document',
    );
    if (mounted) await open(doc, initial: action);
  }

  void message(String value) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(value)));
    }
  }

  Future<void> organize(ScanDocument doc) async {
    var draft = doc.folder;
    final folders =
        documents
            .map((d) => d.folder)
            .where((f) => f.isNotEmpty)
            .toSet()
            .toList()
          ..sort();
    final selected = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Move to folder'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                initialValue: draft,
                maxLength: 60,
                onChanged: (v) => draft = v,
                decoration: const InputDecoration(
                  labelText: 'New or existing folder',
                  helperText: 'Leave empty for Unfiled.',
                ),
              ),
              if (folders.isNotEmpty) const Text('Or choose a folder:'),
              ...folders.map(
                (f) => TextButton(
                  onPressed: () => Navigator.pop(context, f),
                  child: Text(f),
                ),
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
            onPressed: () => Navigator.pop(context, draft.trim()),
            child: const Text('Move'),
          ),
        ],
      ),
    );
    if (selected == null || !mounted) return;
    setState(() => managing = true);
    final previous = doc.folder;
    try {
      doc.folder = selected;
      await widget.store.save(doc);
      await reload();
      message(selected.isEmpty ? 'Moved to Unfiled.' : 'Moved to $selected.');
    } catch (e) {
      doc.folder = previous;
      message(friendlyError(e, 'Could not move the document. Try again.'));
    } finally {
      if (mounted) setState(() => managing = false);
    }
  }

  Future<void> delete(ScanDocument doc) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('Delete “${doc.title}”?'),
        content: Text(
          'Permanently remove ${countLabel(doc.pages.length, 'page')}, their saved text, original copies, and exports stored inside this app. '
          'Files you imported from or shared to other apps will stay. This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete document'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => managing = true);
    try {
      await widget.store.delete(doc);
      await reload();
      message(
        'Document deleted. Storage used by this document has been freed.',
      );
    } catch (e) {
      message(friendlyError(e, 'Could not delete the document. Try again.'));
    } finally {
      if (mounted) setState(() => managing = false);
    }
  }

  Widget action(IconData icon, String title, String subtitle, String kind) {
    final scheme = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final primary = dark && kind == 'camera';
    final foreground = primary ? scheme.onPrimary : scheme.onSurface;
    return Padding(
      padding: EdgeInsets.only(bottom: dark ? 16 : 12),
      child: MergeSemantics(
        child: Semantics(
          button: true,
          child: Card(
            color: primary ? scheme.primary : null,
            child: InkWell(
              borderRadius: BorderRadius.circular(12),
              onTap: () => create(kind),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Row(
                  children: [
                    Icon(icon, size: 30, color: foreground),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            title,
                            style: TextStyle(
                              fontSize: 21,
                              fontWeight: FontWeight.w600,
                              color: foreground,
                            ),
                          ),
                          Text(
                            subtitle,
                            style: dark
                                ? TextStyle(
                                    color: primary
                                        ? scheme.onPrimary
                                        : scheme.onSurfaceVariant,
                                  )
                                : null,
                          ),
                        ],
                      ),
                    ),
                    Icon(Icons.arrow_forward, color: foreground),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('VeriScript'),
      actions: [
        Padding(
          padding: const EdgeInsets.only(right: 20),
          child: Center(
            child: Text(
              'ON DEVICE',
              semanticsLabel: 'Everything stays on this device',
              style: TextStyle(
                fontSize: 14,
                letterSpacing: 1.5,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
        ),
      ],
    ),
    body: SafeArea(
      child: tab == 2
          ? settings()
          : ListView(
              padding: const EdgeInsets.all(24),
              children: [
                if (error != null)
                  Semantics(liveRegion: true, child: Text(error!)),
                if (tab == 0) ...[
                  Semantics(
                    header: true,
                    child: Text(
                      'From paper\nto possibility.',
                      style: Theme.of(context).textTheme.displayLarge,
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Capture a stack of pages. Make it a document.\nEverything stays on your phone.',
                    style: TextStyle(fontSize: 17),
                  ),
                  const SizedBox(height: 28),
                  action(
                    Icons.document_scanner_outlined,
                    'Scan pages',
                    'Take multiple photos before converting.',
                    'camera',
                  ),
                  action(
                    Icons.menu_book_outlined,
                    'Video to book',
                    'Record spreads, then review the captured pages.',
                    'video',
                  ),
                  action(
                    Icons.add_photo_alternate_outlined,
                    'Import',
                    'Choose images or a PDF from your phone.',
                    'import',
                  ),
                  const SizedBox(height: 20),
                ],
                Row(
                  children: [
                    Expanded(
                      child: Semantics(
                        header: true,
                        child: Text(
                          tab == 0 ? 'Recent documents' : 'Your documents',
                          style: const TextStyle(
                            fontSize: 22,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ),
                    if (tab == 1)
                      IconButton(
                        tooltip: 'New document',
                        onPressed: managing ? null : () => create('import'),
                        icon: const Icon(Icons.add),
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                if (tab == 1) ...[
                  TextField(
                    controller: searchController,
                    onChanged: (value) => setState(() => query = value),
                    decoration: const InputDecoration(
                      labelText: 'Search documents',
                      hintText: 'Name, folder, or recognized text',
                      prefixIcon: Icon(Icons.search),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      FilterChip(
                        label: const Text('All'),
                        selected: folder == null,
                        onSelected: (_) => setState(() => folder = null),
                      ),
                      FilterChip(
                        label: const Text('Unfiled'),
                        selected: folder == '',
                        onSelected: (_) => setState(() => folder = ''),
                      ),
                      ...(documents
                              .map((d) => d.folder)
                              .where((f) => f.isNotEmpty)
                              .toSet()
                              .toList()
                            ..sort())
                          .map(
                            (f) => FilterChip(
                              label: Text(f),
                              selected: folder == f,
                              onSelected: (_) => setState(() => folder = f),
                            ),
                          ),
                      if (folder != null &&
                          folder!.isNotEmpty &&
                          !documents.any((d) => d.folder == folder))
                        FilterChip(
                          label: Text(folder!),
                          selected: true,
                          onSelected: (_) => setState(() => folder = null),
                        ),
                    ],
                  ),
                  const SizedBox(height: 16),
                ],
                if (visibleDocuments.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 24),
                    child: Text(
                      documents.isEmpty
                          ? 'Your scanned pages and exports will appear here.'
                          : 'No matching documents. Try another search or folder.',
                    ),
                  ),
                ...visibleDocuments
                    .take(tab == 0 ? 5 : documents.length)
                    .map(
                      (doc) => Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Card(
                          child: ListTile(
                            contentPadding: const EdgeInsets.all(12),
                            leading: doc.pages.isEmpty
                                ? const Icon(Icons.description_outlined)
                                : Image.file(
                                    File(doc.pages.first.path),
                                    width: 48,
                                    height: 64,
                                    fit: BoxFit.cover,
                                    cacheWidth: 120,
                                    errorBuilder: (_, _, _) =>
                                        const Icon(Icons.broken_image_outlined),
                                  ),
                            title: Text(doc.title),
                            subtitle: Text(
                              '${countLabel(doc.pages.length, 'page')} · ${countLabel(doc.exports.length, 'export')}${doc.folder.isEmpty ? '' : '\n${doc.folder}'}',
                            ),
                            trailing: PopupMenuButton<String>(
                              tooltip: 'Manage ${doc.title}',
                              enabled: !managing,
                              onSelected: (value) {
                                if (value == 'folder') {
                                  organize(doc);
                                } else {
                                  delete(doc);
                                }
                              },
                              itemBuilder: (_) => const [
                                PopupMenuItem(
                                  value: 'folder',
                                  child: Text('Move to folder'),
                                ),
                                PopupMenuItem(
                                  value: 'delete',
                                  child: Text('Delete document'),
                                ),
                              ],
                            ),
                            onTap: managing ? null : () => open(doc),
                          ),
                        ),
                      ),
                    ),
              ],
            ),
    ),
    bottomNavigationBar: NavigationBar(
      selectedIndex: tab,
      onDestinationSelected: (index) => setState(() => tab = index),
      destinations: const [
        NavigationDestination(
          icon: Icon(Icons.home_outlined),
          selectedIcon: Icon(Icons.home),
          label: 'Home',
        ),
        NavigationDestination(
          icon: Icon(Icons.folder_outlined),
          selectedIcon: Icon(Icons.folder),
          label: 'Files',
        ),
        NavigationDestination(icon: Icon(Icons.tune), label: 'Settings'),
      ],
    ),
  );
  Widget settings() => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      Semantics(
        header: true,
        child: Text(
          'Make yourself at home.',
          style: Theme.of(context).textTheme.displayMedium,
        ),
      ),
      const SizedBox(height: 24),
      DropdownButtonFormField<int>(
        isExpanded: true,
        initialValue: widget.settings.getInt('theme') ?? 0,
        decoration: const InputDecoration(labelText: 'Appearance'),
        items:
            {
                  0: 'Follow system',
                  1: 'Paper & Ink · light',
                  2: 'Night Studio · dark',
                }.entries
                .map(
                  (entry) => DropdownMenuItem(
                    value: entry.key,
                    child: SelectionLabel(
                      entry.value,
                      selected:
                          entry.key == (widget.settings.getInt('theme') ?? 0),
                    ),
                  ),
                )
                .toList(),
        onChanged: (v) async {
          await widget.settings.setInt('theme', v!);
          widget.onAppearance();
          if (mounted) setState(() {});
        },
      ),
      const SizedBox(height: 20),
      DropdownButtonFormField<String>(
        isExpanded: true,
        initialValue: widget.settings.getString('language') ?? 'ne',
        decoration: const InputDecoration(labelText: 'OCR language'),
        items:
            {
                  'ne': 'Nepali · Devanagari',
                  'hi': 'Hindi · Devanagari',
                  'en': 'English · Latin',
                }.entries
                .map(
                  (entry) => DropdownMenuItem(
                    value: entry.key,
                    child: SelectionLabel(
                      entry.value,
                      selected:
                          entry.key ==
                          (widget.settings.getString('language') ?? 'ne'),
                    ),
                  ),
                )
                .toList(),
        onChanged: (v) async {
          await widget.settings.setString('language', v!);
          if (mounted) setState(() {});
        },
      ),
      const SizedBox(height: 16),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Desktop reader (preview)'),
        subtitle: const Text(
          'Uses the PC recognition models offline. Can be slower and make different errors. '
          'Check the result against the page.',
        ),
        value: widget.settings.getString('ocrEngine') == 'rapidocr',
        onChanged: (v) async {
          await widget.settings.setString(
            'ocrEngine',
            v ? 'rapidocr' : 'mlkit',
          );
          if (mounted) setState(() {});
        },
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Automatic alignment'),
        subtitle: const Text('Detect page edges and straighten small tilts.'),
        value: widget.settings.getBool('align') ?? true,
        onChanged: (v) async {
          await widget.settings.setBool('align', v);
          setState(() {});
        },
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Document enhancement'),
        subtitle: const Text(
          'Reduce shadows and enlarge small pages up to 2×. Originals are kept.',
        ),
        value: widget.settings.getBool('enhance') ?? true,
        onChanged: (v) async {
          await widget.settings.setBool('enhance', v);
          setState(() {});
        },
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Digit re-read checks'),
        subtitle: const Text(
          'Compare enlarged crops; flag disagreements without replacing numbers.',
        ),
        value: widget.settings.getBool('digits') ?? true,
        onChanged: (v) async {
          await widget.settings.setBool('digits', v);
          setState(() {});
        },
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Automatic text orientation'),
        subtitle: const Text('Check upright direction during OCR.'),
        value: widget.settings.getBool('rotate') ?? true,
        onChanged: (v) async {
          await widget.settings.setBool('rotate', v);
          setState(() {});
        },
      ),
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.photo_camera_back_outlined),
        title: const Text('Camera diagnostics'),
        subtitle: const Text(
          'Read this device\'s camera capabilities. No photo is taken.',
        ),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => const ScanDiagnosticsScreen(),
          ),
        ),
      ),
      const SizedBox(height: 24),
      Semantics(
        header: true,
        child: const Text(
          'Offline by design',
          style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
        ),
      ),
      const Text(
        'OCR models and image processing are bundled. No account, server or first-run model download. Sharing opens an app you choose.',
      ),
      const SizedBox(height: 16),
      const Text(
        'Android 10 or newer. Target: 4 GB RAM, 2 GB free space; 6 GB RAM and more storage for long books. These performance targets still need physical-phone tests.',
      ),
      const SizedBox(height: 16),
      const Text(
        'Video capture is experimental. Check crops, ordering, completeness, names and numbers before export. Curved pages may need a retake. Mobile OCR uses ML Kit; accuracy differs from the desktop engine.',
      ),
      const SizedBox(height: 16),
      TextButton(
        onPressed: () => showLicensePage(
          context: context,
          applicationName: 'VeriScript',
          applicationVersion: '0.1.0',
        ),
        child: const Text('Open-source licenses'),
      ),
    ],
  );
}
