import 'dart:async';
import 'dart:developer' as dev;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:local_auth/local_auth.dart';
import 'package:local_auth/error_codes.dart' as auth_error;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/theme.dart';

/// Wraps any child widget and enforces the app-lock (biometric / device PIN)
/// when [biometric_auth] is enabled in SharedPreferences.
///
/// Design decisions:
///   - [_lockEnabled] is cached so that [_lockIfEnabled] is fully synchronous,
///     eliminating the async race where a completed unlock is overwritten.
///   - A generation counter ([_authGen]) discards stale auth results caused by
///     rapid lifecycle transitions (e.g. app goes background then foreground
///     again before the previous auth dialog was dismissed).
///   - A post-unlock cooldown ([_lastUnlockedAt]) prevents immediately
///     re-locking within 3 s of a successful unlock.
///   - [AppLifecycleState.inactive] is a no-op: iOS fires it when the biometric
///     dialog appears, and Android fires it for transient focus loss.  Acting on
///     it would cause an infinite lock loop.
///   - Auth uses [local_auth] directly (not StorageService) so that raw
///     [PlatformException] error codes are accessible for user-friendly messages.
class BiometricGate extends StatefulWidget {
  final Widget child;
  const BiometricGate({super.key, required this.child});

  @override
  State<BiometricGate> createState() => _BiometricGateState();
}

class _BiometricGateState extends State<BiometricGate>
    with WidgetsBindingObserver {
  // ── State ─────────────────────────────────────────────────────────────────

  /// Whether the lock screen is currently visible.
  bool _locked = false;

  /// True while loading the initial preference — no spinner, just blank bg.
  bool _initialising = true;

  /// True while a biometric/PIN prompt is in flight.
  bool _authenticating = false;

  /// User-visible error message shown on the lock screen.
  String? _authError;

  // ── Race-condition guards ─────────────────────────────────────────────────

  /// Cached value of biometric_auth pref — kept in sync on resume.
  /// Making the lock decision synchronous eliminates the async race between
  /// _lockIfEnabled() and a concurrently completing auth prompt.
  bool _lockEnabled = false;

  /// Timestamp of the last successful unlock.  Prevents re-locking within
  /// [_cooldown] of a successful unlock (e.g. biometric dialog fires paused).
  DateTime? _lastUnlockedAt;
  static const _cooldown = Duration(seconds: 3);

  /// Incremented at the start of every auth attempt.  If the value has changed
  /// by the time auth returns, the result belongs to a superseded attempt and
  /// is silently discarded.
  int _authGen = 0;

  // ── Auth backend ──────────────────────────────────────────────────────────

  final _localAuth = LocalAuthentication();

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _init();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    dev.log('lifecycle → $state', name: 'BiometricGate');
    switch (state) {
      case AppLifecycleState.paused:
      case AppLifecycleState.hidden:
      case AppLifecycleState.detached:
        // Lock synchronously — no async, so a concurrent auth completion
        // cannot race against this.
        _lockIfEnabled();
        break;

      case AppLifecycleState.resumed:
        // Re-read pref (user may have toggled it in Settings), then prompt.
        _onResumed();
        break;

      case AppLifecycleState.inactive:
        // Intentional no-op.
        // iOS: fires when the biometric dialog is presented.
        // Android: fires on transient focus loss (notification shade, etc.).
        // Locking here would cause an infinite lock → auth → inactive → lock loop.
        break;
    }
  }

  // ── Initialisation ────────────────────────────────────────────────────────

  Future<void> _init() async {
    dev.log('init — reading biometric_auth pref', name: 'BiometricGate');
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;

    _lockEnabled = prefs.getBool('biometric_auth') ?? false;
    dev.log('init — lockEnabled=$_lockEnabled', name: 'BiometricGate');

    if (_lockEnabled) {
      setState(() {
        _locked = true;
        _initialising = false;
      });
      await _promptAuth();
    } else {
      setState(() {
        _initialising = false;
      });
    }
  }

  // ── Core helpers ──────────────────────────────────────────────────────────

  /// Synchronous lock — no await, so it cannot race against auth completion.
  void _lockIfEnabled() {
    if (!_lockEnabled) return;
    if (_authenticating) {
      // Biometric dialog is active — it is the cause of the paused/hidden event.
      dev.log('lock skipped — auth in flight', name: 'BiometricGate');
      return;
    }
    if (_lastUnlockedAt != null &&
        DateTime.now().difference(_lastUnlockedAt!) < _cooldown) {
      dev.log('lock skipped — within cooldown', name: 'BiometricGate');
      return;
    }
    dev.log('locking', name: 'BiometricGate');
    if (mounted) setState(() => _locked = true);
  }

  Future<void> _onResumed() async {
    // Refresh cached setting — the user may have changed it while in Settings.
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;
    _lockEnabled = prefs.getBool('biometric_auth') ?? false;
    dev.log('resumed — lockEnabled=$_lockEnabled, locked=$_locked', name: 'BiometricGate');

    if (!_locked || _authenticating) return;

    // Honour cooldown — if we unlocked very recently (e.g. fingerprint was
    // accepted, then the resumed event arrived late), don't re-prompt.
    if (_lastUnlockedAt != null &&
        DateTime.now().difference(_lastUnlockedAt!) < _cooldown) {
      dev.log('resumed — within cooldown, unlocking silently', name: 'BiometricGate');
      if (mounted) setState(() => _locked = false);
      return;
    }

    dev.log('resumed — prompting auth', name: 'BiometricGate');
    await _promptAuth();
  }

  // ── Authentication ────────────────────────────────────────────────────────

  Future<void> _promptAuth() async {
    if (_authenticating || !mounted) return;

    dev.log('auth start — checking availability', name: 'BiometricGate');

    // Availability pre-check prevents a permanent lockout when the device has
    // no lock set (e.g. factory reset, or lock disabled in OS settings).
    final available = await _checkAvailability();
    if (!mounted) return;
    if (!available) return; // _authError set inside _checkAvailability

    // Capture generation before the async gap.
    final gen = ++_authGen;
    dev.log('auth gen=$gen — prompting', name: 'BiometricGate');

    setState(() {
      _authenticating = true;
      _authError = null;
    });

    bool authResult = false;
    String? errorMsg;

    try {
      authResult = await _localAuth
          .authenticate(
            localizedReason: 'Unlock TrustBond to continue',
            options: const AuthenticationOptions(
              biometricOnly: false,
              // stickyAuth keeps the dialog alive across background events on
              // both Android and iOS — prevents dialog dismissal when the app
              // momentarily loses focus during fingerprint read.
              stickyAuth: true,
            ),
          )
          .timeout(
        const Duration(seconds: 30),
        onTimeout: () {
          dev.log('auth gen=$gen timed out', name: 'BiometricGate');
          return false;
        },
      );
    } on PlatformException catch (e) {
      dev.log('auth gen=$gen PlatformException: ${e.code} — ${e.message}',
          name: 'BiometricGate');
      errorMsg = _friendlyError(e.code);
    } catch (e) {
      dev.log('auth gen=$gen unexpected: $e', name: 'BiometricGate');
      errorMsg = 'Authentication unavailable. Please try again.';
    }

    // Discard stale result — another attempt was started after this one.
    if (!mounted || gen != _authGen) {
      dev.log('auth gen=$gen discarded (current gen=$_authGen)', name: 'BiometricGate');
      return;
    }

    dev.log('auth gen=$gen result=$authResult error=$errorMsg',
        name: 'BiometricGate');

    if (authResult) {
      _lastUnlockedAt = DateTime.now();
      setState(() {
        _locked = false;
        _authenticating = false;
        _authError = null;
      });
    } else {
      setState(() {
        _authenticating = false;
        _authError = errorMsg ?? 'Authentication failed. Tap Unlock to try again.';
      });
    }
  }

  /// Returns false and sets [_authError] when biometric/lock is unavailable.
  Future<bool> _checkAvailability() async {
    try {
      final supported = await _localAuth.isDeviceSupported();
      if (!supported) {
        dev.log('availability — device not supported', name: 'BiometricGate');
        if (mounted) {
          setState(() {
            _authError =
                'No device lock detected. Set up a PIN or biometric in your device settings to use app lock.';
          });
        }
        return false;
      }
      return true;
    } on PlatformException catch (e) {
      dev.log('availability check failed: ${e.code}', name: 'BiometricGate');
      if (mounted) {
        setState(() {
          _authError = 'Cannot verify authentication availability.';
        });
      }
      return false;
    }
  }

  /// Maps a [local_auth] error code to a human-readable message.
  /// Never surfaces raw exception text to the user.
  String _friendlyError(String code) {
    switch (code) {
      case auth_error.notAvailable:
        return 'Biometric authentication is not available on this device.';
      case auth_error.notEnrolled:
        return 'No biometrics enrolled. Add a fingerprint or face in Settings → Security.';
      case auth_error.lockedOut:
        return 'Too many failed attempts. Please wait a moment and try again.';
      case auth_error.permanentlyLockedOut:
        return 'Biometrics locked out. Please unlock using your device PIN.';
      case auth_error.passcodeNotSet:
        return 'No screen lock set. Enable a PIN or biometric in device Settings.';
      case auth_error.otherOperatingSystem:
        return 'Authentication is not supported on this platform.';
      default:
        // auth_in_progress, user_cancel, or unknown — treat as cancellation.
        return 'Authentication failed. Tap Unlock to try again.';
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    // During init: show a plain background with no spinner — avoids a brief
    // white flash or spinning indicator before the lock screen appears.
    if (_initialising) {
      return const Scaffold(backgroundColor: AppColors.bg);
    }

    if (_locked) {
      return _LockScreen(
        authenticating: _authenticating,
        authError: _authError,
        onRetry: _promptAuth,
      );
    }

    return widget.child;
  }
}

// ── Lock Screen UI ────────────────────────────────────────────────────────────

class _LockScreen extends StatelessWidget {
  final bool authenticating;
  final String? authError;
  final VoidCallback onRetry;

  const _LockScreen({
    required this.authenticating,
    this.authError,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 44),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Logo with fallback icon in case the asset is missing.
                Container(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(
                        color: AppColors.accent.withValues(alpha: 0.22),
                        blurRadius: 28,
                        spreadRadius: 4,
                      ),
                    ],
                  ),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(22),
                    child: Image.asset(
                      'assets/images/logo.jpeg',
                      width: 80,
                      height: 80,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => Container(
                        width: 80,
                        height: 80,
                        decoration: BoxDecoration(
                          color: AppColors.accent.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(22),
                        ),
                        child: const Icon(
                          Icons.shield_rounded,
                          size: 44,
                          color: AppColors.accent,
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 28),
                const Text(
                  'TrustBond',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 8),
                const Text(
                  'App is locked',
                  style: TextStyle(fontSize: 13, color: AppColors.muted),
                ),
                const SizedBox(height: 44),
                if (authenticating)
                  const Column(
                    children: [
                      CircularProgressIndicator(color: AppColors.accent),
                      SizedBox(height: 16),
                      Text(
                        'Verifying identity…',
                        style: TextStyle(fontSize: 12, color: AppColors.muted),
                      ),
                    ],
                  )
                else ...[
                  if (authError != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 14),
                      child: Text(
                        authError!,
                        style: const TextStyle(
                            fontSize: 12, color: AppColors.danger),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: onRetry,
                      icon: const Icon(Icons.fingerprint_rounded, size: 20),
                      label: const Text('Unlock'),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
