import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'documents.dart';
import 'library.dart';
import 'theme.dart';
import 'welcome.dart';

// The app's public surface for tests and tools.
export 'library.dart' show LibraryScreen;
export 'theme.dart' show studioTheme;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    VeriScriptApp(
      settings: await SharedPreferences.getInstance(),
      store: await DocumentStore.open(),
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
    home: widget.settings.getBool('welcomed') == true
        ? LibraryScreen(
            store: widget.store,
            settings: widget.settings,
            onAppearance: () => setState(() {}),
          )
        : WelcomeScreen(
            onDone: () async {
              await widget.settings.setBool('welcomed', true);
              if (mounted) setState(() {});
            },
          ),
  );
}
