import 'package:flutter/material.dart';

/// TrustBond dark theme colors matching the design system.
class AppColors {
  AppColors._();

  static const Color bg = Color(0xFF0A0F1E);
  static const Color surface = Color(0xFF111827);
  static const Color surface2 = Color(0xFF1A2235);
  static const Color surface3 = Color(0xFF222D42);
  static const Color accent = Color(0xFF00E5B4);
  static const Color accent2 = Color(0xFF0099FF);
  static const Color warn = Color(0xFFFF6B35);
  static const Color danger = Color(0xFFFF3B5C);
  static const Color ok = Color(0xFF00E5B4);
  static const Color text = Color(0xFFEAF0FF);
  static const Color muted = Color(0xFF7A8AAA);
  static const Color border = Color(0xFF1E2D4A);
  static const Color card = Color(0xFF141E30);
}

ThemeData buildAppTheme() {
  return ThemeData(
    brightness: Brightness.dark,
    scaffoldBackgroundColor: AppColors.bg,
    primaryColor: AppColors.accent,
    colorScheme: const ColorScheme.dark(
      primary: AppColors.accent,
      secondary: AppColors.accent2,
      surface: AppColors.surface,
      error: AppColors.danger,
      onPrimary: Colors.black,
      onSecondary: Colors.black,
      onSurface: AppColors.text,
      onError: Colors.white,
    ),
    fontFamily: 'Sora',
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.transparent,
      elevation: 0,
      centerTitle: true,
      titleTextStyle: TextStyle(
        color: AppColors.text,
        fontSize: 19,
        fontWeight: FontWeight.w700,
      ),
      iconTheme: IconThemeData(color: AppColors.text),
    ),
    cardTheme: CardThemeData(
      color: AppColors.card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(22),
        side: const BorderSide(color: AppColors.border),
      ),
      margin: const EdgeInsets.only(bottom: 18),
      elevation: 0,
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.accent,
        foregroundColor: Colors.black,
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        textStyle: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.4,
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.text,
        side: const BorderSide(color: AppColors.border),
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        backgroundColor: AppColors.surface2,
        textStyle: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
        ),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface2,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.accent),
      ),
      labelStyle: const TextStyle(color: AppColors.muted, fontSize: 11, letterSpacing: 0.4),
      hintStyle: const TextStyle(color: AppColors.muted),
      contentPadding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: const Color(0xF7080C18),
      indicatorColor: AppColors.accent.withValues(alpha: 0.08),
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.selected)) {
          return const TextStyle(fontSize: 9, color: AppColors.accent, letterSpacing: 0.4);
        }
        return const TextStyle(fontSize: 9, color: AppColors.muted, letterSpacing: 0.4);
      }),
      iconTheme: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.selected)) {
          return const IconThemeData(color: AppColors.accent, size: 22);
        }
        return const IconThemeData(color: AppColors.muted, size: 22);
      }),
      height: 64,
      elevation: 0,
    ),
    dividerTheme: const DividerThemeData(color: AppColors.border, thickness: 1, space: 0),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: AppColors.surface2,
      contentTextStyle: const TextStyle(color: AppColors.text),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      behavior: SnackBarBehavior.floating,
    ),
    useMaterial3: true,
  );
}
