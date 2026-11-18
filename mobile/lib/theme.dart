import 'package:flutter/material.dart';
import 'theme_tokens.dart';

/// Paper & Ink (light) and Night Studio (dark), from the shared tokens.
ThemeData studioTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  // Shared with the web studio: design/tokens.json → theme_tokens.dart.
  final t = dark ? ThemeTokens.dark : ThemeTokens.light;
  final background = t.paper100;
  final surface = t.paper050;
  final ink = t.ink900;
  final amber = t.amber500;
  final generated = ColorScheme.fromSeed(
    seedColor: amber,
    brightness: brightness,
  );
  final scheme = generated.copyWith(
    surface: surface,
    primary: amber,
    onPrimary: t.onAccent,
    onSurface: ink,
    surfaceContainerHighest: t.paper200,
    onSurfaceVariant: dark ? t.ink500 : generated.onSurfaceVariant,
    surfaceDim: dark ? background : generated.surfaceDim,
    // Material's in-between container steps for Night Studio. They are
    // Android-only (the web has no equivalent surfaces), so they stay here.
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
    outline: dark ? t.lineStrong : generated.outline,
    outlineVariant: dark ? t.line : generated.outlineVariant,
    primaryContainer: dark
        ? const Color(0xff3f321a)
        : generated.primaryContainer,
    onPrimaryContainer: dark ? amber : generated.onPrimaryContainer,
    secondary: dark ? t.ink500 : generated.secondary,
    secondaryContainer: dark ? t.paper200 : generated.secondaryContainer,
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
        foregroundColor: t.amber800,
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
