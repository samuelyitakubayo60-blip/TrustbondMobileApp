import 'package:flutter/material.dart';

/// TrustBond dark theme colors — v2 balanced palette.
///
/// Changes from v1:
///   • success / ok  → #00C896  (distinct from accent #00E5B4)
///   • error         → #FF6080  (distinct from danger #FF3B5C)
///   • muted         → #8D9EC0  (contrast lifted to ~5.0:1 for AA compliance)
///   • surface3      → #26334E  (more separation from surface2)
///   • accent2 text  → #33AAFF  (use for text/icons; keep #0099FF for fills)
class AppColors {
  AppColors._();

  // ── Backgrounds ────────────────────────────────────────────────────────────
  static const Color bg       = Color(0xFF080D1A);  // deeper navy for more contrast
  static const Color surface  = Color(0xFF0F1929);
  static const Color surface2 = Color(0xFF172032);
  static const Color surface3 = Color(0xFF1F2B42);
  static const Color card     = Color(0xFF111B2E);

  // ── Brand / Interactive ────────────────────────────────────────────────────
  /// Primary teal-green — vibrant, energetic.
  static const Color accent   = Color(0xFF00E8B8);

  /// Electric blue — secondary actions, links, info states.
  static const Color accent2  = Color(0xFF2196F3);

  /// Use for blue text / icons on dark surfaces (contrast-safe variant).
  static const Color accent2Text = Color(0xFF64B5F6);

  // ── Semantic ───────────────────────────────────────────────────────────────
  /// Warning — amber-orange, warm and visible.
  static const Color warn    = Color(0xFFFFAB40);

  /// Danger — vivid red-pink for critical actions.
  static const Color danger  = Color(0xFFFF4B70);

  /// OK / success — rich green distinct from accent.
  static const Color ok      = Color(0xFF00D68F);
  static const Color success = Color(0xFF00D68F);

  /// Inline form validation error — softer red.
  static const Color error   = Color(0xFFFF7094);

  // ── Typography ─────────────────────────────────────────────────────────────
  static const Color text   = Color(0xFFEEF4FF);

  /// Hint text, labels, secondary copy — WCAG AA compliant.
  static const Color muted  = Color(0xFF8BA0C0);

  // ── Structural ─────────────────────────────────────────────────────────────
  static const Color border = Color(0xFF1C2C44);
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

    // ── App Bar ──────────────────────────────────────────────────────────────
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

    // ── Cards ────────────────────────────────────────────────────────────────
    cardTheme: CardThemeData(
      color: AppColors.card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(22),
        side: const BorderSide(color: AppColors.border),
      ),
      margin: const EdgeInsets.only(bottom: 18),
      elevation: 0,
    ),

    // ── Buttons ──────────────────────────────────────────────────────────────
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

    // ── Inputs ───────────────────────────────────────────────────────────────
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
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.error),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.error, width: 1.5),
      ),
      labelStyle: const TextStyle(
        color: AppColors.muted,
        fontSize: 11,
        letterSpacing: 0.4,
      ),
      hintStyle: const TextStyle(color: AppColors.muted),
      errorStyle: const TextStyle(color: AppColors.error, fontSize: 11),
      contentPadding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
    ),

    // ── Navigation Bar ───────────────────────────────────────────────────────
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: const Color(0xF7060B16),
      indicatorColor: AppColors.accent.withValues(alpha: 0.14),
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.selected)) {
          return const TextStyle(
            fontSize: 9,
            color: AppColors.accent,
            letterSpacing: 0.4,
          );
        }
        return const TextStyle(
          fontSize: 9,
          color: AppColors.muted,
          letterSpacing: 0.4,
        );
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

    // ── Misc ─────────────────────────────────────────────────────────────────
    dividerTheme: const DividerThemeData(
      color: AppColors.border,
      thickness: 1,
      space: 0,
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: AppColors.surface2,
      contentTextStyle: const TextStyle(color: AppColors.text),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      behavior: SnackBarBehavior.floating,
    ),
    useMaterial3: true,
  );
}