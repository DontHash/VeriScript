import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'documents.dart';
import 'review.dart';

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
  final scheme = ColorScheme.fromSeed(seedColor: amber, brightness: brightness)
      .copyWith(
        surface: surface,
        primary: amber,
        onPrimary: const Color(0xff120e08),
        onSurface: ink,
        surfaceContainerHighest: Color(dark ? 0xff283341 : 0xffe5dfd1),
      );
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(12));
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    fontFamily: 'Mukta',
    colorScheme: scheme,
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
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 48),
        foregroundColor: ink,
        shape: shape,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(minimumSize: const Size(48, 48)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: surface,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
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
  @override
  void initState() {
    super.initState();
    unawaited(reload());
  }

  Future<void> reload() async {
    try {
      final docs = await widget.store.list();
      if (mounted) setState(() => documents = docs);
    } catch (e) {
      if (mounted) setState(() => error = '$e');
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

  Widget action(IconData icon, String title, String subtitle, String kind) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Card(
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: () => create(kind),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Row(
                children: [
                  Icon(icon, size: 30),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          title,
                          style: const TextStyle(
                            fontSize: 21,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        Text(subtitle),
                      ],
                    ),
                  ),
                  const Icon(Icons.arrow_forward),
                ],
              ),
            ),
          ),
        ),
      );
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
              style: TextStyle(
                fontSize: 12,
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
                if (error != null) Text(error!),
                if (tab == 0) ...[
                  const Text(
                    'From paper\nto possibility.',
                    style: TextStyle(
                      fontFamily: 'serif',
                      fontSize: 38,
                      height: 1.15,
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
                    Text(
                      tab == 0 ? 'Recent documents' : 'Your documents',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const Spacer(),
                    if (tab == 1)
                      IconButton(
                        tooltip: 'New document',
                        onPressed: () => create('import'),
                        icon: const Icon(Icons.add),
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                if (documents.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Text(
                      'Your scanned pages and exports will appear here.',
                    ),
                  ),
                ...documents
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
                              '${doc.pages.length} pages · ${doc.exports.length} exports',
                            ),
                            trailing: const Icon(Icons.chevron_right),
                            onTap: () => open(doc),
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
      const Text(
        'Make yourself at home.',
        style: TextStyle(fontFamily: 'serif', fontSize: 30),
      ),
      const SizedBox(height: 24),
      DropdownButtonFormField<int>(
        isExpanded: true,
        initialValue: widget.settings.getInt('theme') ?? 0,
        decoration: const InputDecoration(labelText: 'Appearance'),
        items: const [
          DropdownMenuItem(value: 0, child: Text('Follow system')),
          DropdownMenuItem(value: 1, child: Text('Paper & Ink · light')),
          DropdownMenuItem(value: 2, child: Text('Night Studio · dark')),
        ],
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
        items: const [
          DropdownMenuItem(value: 'ne', child: Text('Nepali · Devanagari')),
          DropdownMenuItem(value: 'hi', child: Text('Hindi · Devanagari')),
          DropdownMenuItem(value: 'en', child: Text('English · Latin')),
        ],
        onChanged: (v) async {
          await widget.settings.setString('language', v!);
        },
      ),
      const SizedBox(height: 16),
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
      const SizedBox(height: 24),
      const Text(
        'Offline by design',
        style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
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
