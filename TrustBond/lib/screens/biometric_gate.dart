import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config/theme.dart';
import '../services/storage_service.dart';

/// Wraps any child widget and enforces the app-lock (biometric / device PIN)
/// when biometric_auth is enabled in settings.
///
/// Behaviour:
///   - On first build: if lock is enabled, overlay the lock screen and prompt immediately.
///   - When app goes to background (paused/hidden): set locked = true so the
///     lock screen appears the instant the user returns.
///   - On resume: trigger auth prompt automatically.
class BiometricGate extends StatefulWidget {
  final Widget child;
  const BiometricGate({super.key, required this.child});

  @override
  State<BiometricGate> createState() => _BiometricGateState();
}

class _BiometricGateState extends State<BiometricGate>
    with WidgetsBindingObserver {
  /// true  = lock screen is visible
  /// false = app content is visible
  bool _locked = false;

  /// true while we're waiting for the initial pref check
  bool _initialising = true;

  /// prevents double-triggering auth
  bool _authenticating = false;

  final _storage = StorageService();

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

  // ── Lifecycle ────────────────────────────────────────────────────────────

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.paused:
      case AppLifecycleState.hidden:
      case AppLifecycleState.detached:
        _lockIfEnabled();
        break;
      case AppLifecycleState.resumed:
        if (_locked) _promptAuth();
        break;
      default:
        break;
    }
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  Future<bool> _lockEnabled() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool('biometric_auth') ?? false;
  }

  Future<void> _init() async {
    final enabled = await _lockEnabled();
    if (!mounted) return;
    if (enabled) {
      setState(() {
        _locked = true;
        _initialising = false;
      });
      await _promptAuth();
    } else {
      setState(() {
        _locked = false;
        _initialising = false;
      });
    }
  }

  Future<void> _lockIfEnabled() async {
    if (await _lockEnabled()) {
      if (mounted) setState(() => _locked = true);
    }
  }

  Future<void> _promptAuth() async {
    if (_authenticating || !mounted) return;
    setState(() => _authenticating = true);

    try {
      final ok = await _storage.authenticateWithBiometrics(
        reason: 'Unlock TrustBond to continue',
      );
      if (!mounted) return;
      if (ok) {
        setState(() {
          _locked = false;
          _authenticating = false;
        });
      } else {
        setState(() => _authenticating = false);
        // stay locked — user can tap "Unlock" to retry
      }
    } catch (_) {
      if (mounted) setState(() => _authenticating = false);
    }
  }

  // ── Build ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    if (_initialising) {
      return const Scaffold(
        backgroundColor: AppColors.bg,
        body: Center(
          child: CircularProgressIndicator(color: AppColors.accent),
        ),
      );
    }

    if (_locked) {
      return _LockScreen(
        authenticating: _authenticating,
        onRetry: _promptAuth,
      );
    }

    return widget.child;
  }
}

// ── Lock Screen UI ───────────────────────────────────────────────────────────

class _LockScreen extends StatelessWidget {
  final bool authenticating;
  final VoidCallback onRetry;

  const _LockScreen({required this.authenticating, required this.onRetry});

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
                // Logo
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
                  Column(
                    children: [
                      const CircularProgressIndicator(color: AppColors.accent),
                      const SizedBox(height: 16),
                      const Text(
                        'Verifying identity…',
                        style: TextStyle(fontSize: 12, color: AppColors.muted),
                      ),
                    ],
                  )
                else
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: onRetry,
                      icon: const Icon(Icons.fingerprint_rounded, size: 20),
                      label: const Text('Unlock'),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
