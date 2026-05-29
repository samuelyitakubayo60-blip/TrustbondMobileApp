import 'package:flutter/material.dart';

/// TrustBond dark theme colors — v3 dashboard-aligned palette.
///
/// All tokens mirror the web dashboard's dark-mode CSS variables so
/// that the mobile app and dashboard share the same visual identity:
///
///   bg         →  --bg: #0d1117
///   surface    →  --surface / --bg-deep: #161b22
///   surface2   →  --surface2: #1f2733
///   surface3   →  --surface3: #28303d
///   accent     →  --accent: #60a5fa  (blue-400, was teal)
///   accent2    →  --cyan: #22d3ee
///   warn       →  --warning: #fbbf24
///   danger     →  --danger: #f87171
///   ok/success →  --success: #34d399
///   text       →  --text: #e2e8f0
///   muted      →  --text-dim: #94a3b8
///   border     →  rgba(255,255,255,0.08) on #0d1117 ≈ #1e2530
class AppColors {
  AppColors._();

  // ── Backgrounds ────────────────────────────────────────────────────────────
  static const Color bg       = Color(0xFF0D1117);  // --bg
  static const Color surface  = Color(0xFF161B22);  // --surface / bg-deep
  static const Color surface2 = Color(0xFF1F2733);  // --surface2
  static const Color surface3 = Color(0xFF28303D);  // --surface3
  static const Color card     = Color(0xFF161B22);  // cards float on bg

  // ── Brand / Interactive ────────────────────────────────────────────────────
  /// Primary blue-400 — matches dashboard --accent in dark mode.
  static const Color accent   = Color(0xFF60A5FA);

  /// Cyan — dashboard --cyan, secondary actions and highlights.
  static const Color accent2  = Color(0xFF22D3EE);

  /// Lighter blue for text/icons on dark surfaces (contrast-safe).
  static const Color accent2Text = Color(0xFF93C5FD);

  // ── Semantic ───────────────────────────────────────────────────────────────
  /// Warning — amber, matches dashboard --warning: #fbbf24.
  static const Color warn    = Color(0xFFFBBF24);

  /// Danger — red-400, matches dashboard --danger: #f87171.
  static const Color danger  = Color(0xFFF87171);

  /// Success — emerald-400, matches dashboard --success: #34d399.
  static const Color ok      = Color(0xFF34D399);
  static const Color success = Color(0xFF34D399);

  /// Error — same hue as danger for consistency.
  static const Color error   = Color(0xFFF87171);

  // ── Typography ─────────────────────────────────────────────────────────────
  /// Body text — matches dashboard --text: #e2e8f0.
  static const Color text   = Color(0xFFE2E8F0);

  /// Secondary/muted — matches dashboard --text-dim: #94a3b8.
  static const Color muted  = Color(0xFF94A3B8);

  // ── Structural ─────────────────────────────────────────────────────────────
  /// Subtle border — rgba(255,255,255,0.08) approximated as solid.
  static const Color border = Color(0xFF1E2530);
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
      // blue-400 accent is light enough that dark text reads better on it
      onPrimary: Color(0xFF0F172A),
      onSecondary: Color(0xFF0F172A),
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
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: AppColors.border),
      ),
      margin: const EdgeInsets.only(bottom: 16),
      elevation: 0,
    ),

    // ── Buttons ──────────────────────────────────────────────────────────────
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.accent,
        foregroundColor: const Color(0xFF0F172A),  // dark text on blue
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
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
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
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
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.accent),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.error),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
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
      backgroundColor: const Color(0xF20D1117),   // bg at ~95% opacity
      indicatorColor: AppColors.accent.withValues(alpha: 0.16),
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
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      behavior: SnackBarBehavior.floating,
    ),
    useMaterial3: true,
  );
}