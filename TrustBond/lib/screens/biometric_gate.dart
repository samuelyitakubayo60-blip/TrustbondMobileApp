import 'dart:async';
import 'dart:developer' as dev;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:local_auth/local_auth.dart';
import 'package:local_auth/error_codes.dart' as auth_error;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/theme.dart';

// ── State machine ─────────────────────────────────────────────────────────────

/// All possible states of the [BiometricGate].
/// Every UI rendering decision and every lifecycle transition is driven by this
/// enum — there is no combination of booleans that can become inconsistent.
enum _LockState {
  /// Reading SharedPreferences on first launch.
  /// Screen shows a plain background; no spinner, no flicker.
  initialising,

  /// User has been authenticated.  App content is visible.
  unlocked,

  /// App is locked.  Lock screen is idle; no prompt is in flight.
  locked,

  /// OS biometric / PIN dialog is open.
  /// Lock screen is visible with a progress indicator.
  authenticating,

  /// Last auth attempt ended in cancellation, failure, timeout, or
  /// an unavailability condition.  Lock screen shows an error + Unlock button.
  error,
}

// ── Auth outcome ──────────────────────────────────────────────────────────────

/// Distinct outcomes of a single authentication attempt.
/// Each maps to a different user-facing message.
enum _AuthOutcome {
  success,
  cancelled,    // user dismissed the dialog (back button, "Cancel")
  failed,       // wrong biometric / wrong PIN
  timedOut,     // 30-second watchdog elapsed
  unavailable,  // no biometrics enrolled, no PIN set, hardware locked out
}

// ── BiometricGate ─────────────────────────────────────────────────────────────

/// Wraps any child widget and enforces the app-lock (biometric / device PIN)
/// when `biometric_auth` is `true` in SharedPreferences.
///
/// Security guarantees
/// ───────────────────
/// • The lock screen is the ONLY path back to [child].  Every path that sets
///   [_LockState.unlocked] must go through a successful [_AuthOutcome.success].
/// • [_onBackground] locks on EVERY [paused]/[hidden]/[detached] event, with
///   only two safe exceptions:
///     1. The biometric dialog itself causes [paused] — skip to avoid killing
///        the in-flight prompt.
///     2. [_lastUnlockedAt] is within [_unlockCooldown] — skip because the
///        [paused] was fired by the dialog dismissing after a successful auth.
/// • No automatic unlock based on background duration (removed — that was a
///   bypass: any attacker who could trigger a brief focus loss could unlock
///   the app without biometrics).
///
/// Loop prevention
/// ───────────────
/// • [_postPromptWindow] suppresses the 1-2 [resumed] events that Android fires
///   when the biometric Activity closes.
/// • [_unlockCooldown] in [_onResumed] silently clears a late-arriving lock
///   after a successful auth completes.
/// • [_authGen] discards stale results from superseded auth attempts.
/// • [_state == authenticating] blocks [_onBackground] from re-locking and
///   blocks concurrent [_promptAuth] calls.
class BiometricGate extends StatefulWidget {
  final Widget child;
  const BiometricGate({super.key, required this.child});

  @override
  State<BiometricGate> createState() => _BiometricGateState();
}

class _BiometricGateState extends State<BiometricGate>
    with WidgetsBindingObserver {

  // ── State machine ─────────────────────────────────────────────────────────

  _LockState _state = _LockState.initialising;

  /// User-facing message shown when [_state == _LockState.error].
  String? _errorMessage;

  // ── Cached setting ────────────────────────────────────────────────────────

  /// Cached value of `biometric_auth`.  Refreshed on [_init] and every
  /// [resumed] event.  A plain bool — [_onBackground] is synchronous and
  /// cannot race against an async prefs read.
  bool _lockEnabled = false;

  // ── Timing guards ─────────────────────────────────────────────────────────

  /// Stamped on every successful unlock.  [_onBackground] skips starting the
  /// lock timer within [_unlockCooldown] — the biometric dialog fires [paused]
  /// on some devices immediately after delivering the auth result.
  DateTime? _lastUnlockedAt;
  static const _unlockCooldown = Duration(seconds: 3);

  /// Pending lock timer started by [_onBackground].
  /// If [_onResumed] fires before it expires the timer is cancelled — the
  /// backgrounding was a brief OS interruption (volume bar, notification, etc.)
  /// and the app should stay unlocked.  The timer fires only when the app has
  /// been genuinely backgrounded for [_lockDelay].
  Timer? _lockTimer;
  static const _lockDelay = Duration(seconds: 5);

  /// Stamped just before [_localAuth.authenticate()] is called.
  /// [_onResumed] ignores all [resumed] events within [_postPromptWindow] of
  /// this stamp — Android fires 1-2 rapid [resumed] events as the biometric
  /// Activity closes, and we must not re-trigger auth for those.
  DateTime? _lastPromptStartedAt;
  static const _postPromptWindow = Duration(seconds: 4);

  // ── Concurrency guard ─────────────────────────────────────────────────────

  /// Incremented each time a new auth attempt starts.  When the future
  /// resolves, if [_authGen] no longer matches the captured generation the
  /// result is from a superseded attempt and is silently discarded.
  int _authGen = 0;

  // ── Auth backend ──────────────────────────────────────────────────────────

  final _localAuth = LocalAuthentication();

  // ── Derived predicates ────────────────────────────────────────────────────

  bool get _isLocked =>
      _state == _LockState.locked ||
      _state == _LockState.authenticating ||
      _state == _LockState.error;

  // ── Widget lifecycle ──────────────────────────────────────────────────────

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _init();
  }

  @override
  void dispose() {
    _lockTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _log('lifecycle', 'event=$state  appState=$_state');
    switch (state) {
      case AppLifecycleState.paused:
      case AppLifecycleState.hidden:
      case AppLifecycleState.detached:
        _onBackground();
        break;

      case AppLifecycleState.resumed:
        _onResumed();
        break;

      case AppLifecycleState.inactive:
        // Intentional no-op.
        // iOS:     fired when Face ID / Touch ID sheet is presented.
        // Android: fired on any transient focus loss (volume bar, etc.).
        // Reacting here causes: lock → prompt → inactive → lock (infinite loop).
        _log('lifecycle', 'inactive ignored');
        break;
    }
  }

  // ── Initialisation ────────────────────────────────────────────────────────

  Future<void> _init() async {
    _log('init', 'reading biometric_auth preference');
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;

    _lockEnabled = prefs.getBool('biometric_auth') ?? false;
    _log('init', 'lockEnabled=$_lockEnabled');

    if (_lockEnabled) {
      _transition(_LockState.locked);
      await _promptAuth();
    } else {
      _transition(_LockState.unlocked);
    }
  }

  // ── Background ────────────────────────────────────────────────────────────

  /// Called synchronously on every background lifecycle event.
  /// Fully synchronous — no awaits — so it cannot race against a completing
  /// auth future.
  ///
  /// Does NOT lock immediately.  Instead it starts [_lockTimer].  If the app
  /// returns to the foreground before the timer fires (brief interruption such
  /// as a volume bar, notification shade, or permission dialog) [_onResumed]
  /// cancels the timer and the lock state is unchanged.  Only a genuine
  /// background of [_lockDelay] or more causes the app to lock.
  void _onBackground() {
    // Auth dialog is open — Android fires [paused] when the biometric Activity
    // takes focus.  Ignore completely; the dialog manages its own lifecycle.
    if (_state == _LockState.authenticating) {
      _log('background', 'skipped — auth dialog open');
      return;
    }

    if (!_lockEnabled) return;

    // The biometric dialog fires [paused] on some devices immediately after
    // delivering a successful auth result.  Skip to avoid kicking off a lock
    // timer milliseconds after the user just authenticated.
    if (_lastUnlockedAt != null &&
        DateTime.now().difference(_lastUnlockedAt!) < _unlockCooldown) {
      _log('background', 'skipped — within post-unlock cooldown');
      return;
    }

    // Only start the timer from [unlocked].  If the app is already locked or
    // in error state a timer is unnecessary.
    if (_state != _LockState.unlocked) return;

    // (Re-)start the timer.  If a previous timer is still ticking (multiple
    // rapid [paused] events) reset it to avoid a double-fire.
    _lockTimer?.cancel();
    _log('background', 'starting ${_lockDelay.inSeconds}s lock timer');
    _lockTimer = Timer(_lockDelay, () {
      if (!mounted) return;
      if (_lockEnabled && _state == _LockState.unlocked) {
        _log('lockTimer', 'fired — locking');
        _transition(_LockState.locked);
      }
    });
  }

  // ── Resumed ───────────────────────────────────────────────────────────────

  Future<void> _onResumed() async {
    // Cancel any pending lock timer and check whether it was still ticking.
    // • Timer still active  → app was backgrounded for less than [_lockDelay]
    //                          (brief interruption — volume bar, notification
    //                          shade, permission dialog).  Cancel it and bail
    //                          out immediately; state stays [unlocked].
    // • Timer already fired → app was genuinely backgrounded; state is now
    //                          [locked]; fall through to the auth prompt.
    // • Timer is null       → no backgrounding happened before this resumed
    //                          (e.g. initial launch or already locked).
    final wasTimerActive = _lockTimer?.isActive ?? false;
    _lockTimer?.cancel();
    _lockTimer = null;

    // Post-prompt window: absorb the 1-2 rapid [resumed] events that Android
    // fires when the biometric Activity closes.  The auth result is already
    // being processed; do not re-trigger another prompt.
    if (_lastPromptStartedAt != null &&
        DateTime.now().difference(_lastPromptStartedAt!) < _postPromptWindow) {
      _log('resumed', 'within post-prompt window — skipped');
      return;
    }

    // Brief interruption — lock timer was cancelled before it fired, so the
    // app was only away for less than [_lockDelay].  Treat as if the user
    // never left (they were answering a permission dialog, pulling down the
    // notification shade, etc.).
    if (wasTimerActive) {
      _log('resumed', 'brief interruption — lock timer cancelled, no re-lock');
      return;
    }

    // Refresh cached setting — user may have toggled biometric lock in
    // the Settings screen while the app was in background.
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;

    final previous = _lockEnabled;
    _lockEnabled = prefs.getBool('biometric_auth') ?? false;
    if (previous != _lockEnabled) {
      _log('resumed', 'lockEnabled changed: $previous → $_lockEnabled');
    }

    // Lock was disabled while app was in background — unlock immediately,
    // no auth required.
    if (!_lockEnabled && _isLocked) {
      _log('resumed', 'lock disabled — unlocking without prompt');
      _transition(_LockState.unlocked);
      return;
    }

    // Nothing to do if already unlocked or mid-authentication.
    if (!_isLocked || _state == _LockState.authenticating) return;

    // Post-unlock cooldown: auth completed successfully but this [resumed]
    // arrived after the async prefs read.  Clear the lock silently.
    if (_lastUnlockedAt != null &&
        DateTime.now().difference(_lastUnlockedAt!) < _unlockCooldown) {
      _log('resumed', 'within post-unlock cooldown — clearing lock silently');
      _transition(_LockState.unlocked);
      return;
    }

    _log('resumed', 'locked — prompting');
    await _promptAuth();
  }

  // ── Authentication ────────────────────────────────────────────────────────

  Future<void> _promptAuth() async {
    // Only begin auth from a locked or error state.
    // This prevents duplicate auth flows if called from multiple sites
    // (e.g. Unlock button AND a concurrent lifecycle event).
    if (_state != _LockState.locked && _state != _LockState.error) {
      _log('auth', 'skipped — state=$_state');
      return;
    }
    if (!mounted) return;

    _transition(_LockState.authenticating);

    // Availability check — prevents permanent lockout on unconfigured devices.
    final check = await _checkAvailability();
    if (!mounted) return;
    if (!check.available) {
      _log('auth', 'unavailable: ${check.reason}');
      _transitionError(check.reason!);
      return;
    }

    final gen = ++_authGen;
    _lastPromptStartedAt = DateTime.now();
    _log('auth', 'gen=$gen starting dialog');

    _AuthOutcome outcome = _AuthOutcome.failed;
    String? errorMessage;
    bool timedOut = false;

    try {
      final result = await _localAuth
          .authenticate(
            localizedReason: 'Unlock TrustBond to continue',
            options: const AuthenticationOptions(
              biometricOnly: false,
              // stickyAuth: true keeps the dialog alive if the app loses focus
              // momentarily (Android focus events during fingerprint scan).
              stickyAuth: true,
            ),
          )
          .timeout(
        const Duration(seconds: 30),
        onTimeout: () {
          timedOut = true;
          _log('auth', 'gen=$gen timed out after 30 s');
          return false;
        },
      );

      if (timedOut) {
        outcome = _AuthOutcome.timedOut;
      } else if (result) {
        outcome = _AuthOutcome.success;
      } else {
        // local_auth returns false for both user-cancel and biometric mismatch
        // without throwing.  We treat both as "cancelled" (dismissed dialog)
        // because we cannot distinguish them without a PlatformException.
        outcome = _AuthOutcome.cancelled;
      }
    } on PlatformException catch (e) {
      _log('auth', 'gen=$gen PlatformException code=${e.code} msg=${e.message}');
      outcome = _outcomeFromCode(e.code);
      errorMessage = _friendlyError(e.code);
    } catch (e) {
      _log('auth', 'gen=$gen unexpected error: $e');
      outcome = _AuthOutcome.failed;
      errorMessage = 'Authentication unavailable. Please try again.';
    }

    _log('auth', 'gen=$gen outcome=$outcome');

    // Discard result if a newer attempt has been started in the meantime.
    if (!mounted || gen != _authGen) {
      _log('auth', 'gen=$gen discarded (current=$_authGen)');
      return;
    }

    _applyOutcome(outcome, errorMessage);
  }

  void _applyOutcome(_AuthOutcome outcome, String? errorMessage) {
    switch (outcome) {
      case _AuthOutcome.success:
        _log('auth', 'success — unlocking');
        _lastUnlockedAt = DateTime.now();
        _transition(_LockState.unlocked);

      case _AuthOutcome.cancelled:
        _log('auth', 'cancelled — waiting for retry');
        _transitionError('Tap Unlock to authenticate.');

      case _AuthOutcome.timedOut:
        _log('auth', 'timed out — waiting for retry');
        _transitionError('Authentication timed out. Tap Unlock to try again.');

      case _AuthOutcome.failed:
        _log('auth', 'failed — waiting for retry');
        _transitionError(
            errorMessage ?? 'Authentication failed. Tap Unlock to try again.');

      case _AuthOutcome.unavailable:
        _log('auth', 'unavailable — showing config error');
        _transitionError(
            errorMessage ?? 'Authentication is unavailable on this device.');
    }
  }

  // ── Availability ──────────────────────────────────────────────────────────

  Future<({bool available, String? reason})> _checkAvailability() async {
    try {
      // Check 1: device supports any auth mechanism at all.
      final deviceSupported = await _localAuth.isDeviceSupported();
      _log('availability', 'deviceSupported=$deviceSupported');
      if (!deviceSupported) {
        return (
          available: false,
          reason: 'This device does not support secure authentication. '
              'Enable a PIN or biometric in Settings.',
        );
      }

      // Check 2: biometric hardware is present and operational.
      final canCheck = await _localAuth.canCheckBiometrics;
      _log('availability', 'canCheckBiometrics=$canCheck');

      // Check 3: enumerate enrolled biometrics (informational).
      final enrolled = await _localAuth.getAvailableBiometrics();
      _log('availability',
          'enrolled=${enrolled.map((e) => e.name).join(", ")}');

      if (!canCheck && enrolled.isEmpty) {
        // No biometrics configured.  biometricOnly: false means local_auth will
        // fall back to device PIN/pattern/password, so this is still usable.
        _log('availability', 'no biometrics — will fall back to device PIN');
      }

      return (available: true, reason: null);
    } on PlatformException catch (e) {
      _log('availability', 'check failed: ${e.code} — ${e.message}');
      return (available: false, reason: _friendlyError(e.code));
    }
  }

  // ── State transitions ─────────────────────────────────────────────────────

  void _transition(_LockState next) {
    if (!mounted) return;
    _log('state', '$_state → $next');
    setState(() {
      _state = next;
      // Clear the error message whenever we leave the error state.
      if (next != _LockState.error) _errorMessage = null;
    });
  }

  void _transitionError(String message) {
    if (!mounted) return;
    _log('state', '$_state → error  msg="$message"');
    setState(() {
      _state = _LockState.error;
      _errorMessage = message;
    });
  }

  // ── Error code mapping ────────────────────────────────────────────────────

  _AuthOutcome _outcomeFromCode(String code) {
    switch (code) {
      case auth_error.notAvailable:
      case auth_error.notEnrolled:
      case auth_error.passcodeNotSet:
      case auth_error.otherOperatingSystem:
      case auth_error.lockedOut:
      case auth_error.permanentlyLockedOut:
        return _AuthOutcome.unavailable;
      default:
        // auth_in_progress or any code containing "cancel" → treat as user cancel.
        if (code.toLowerCase().contains('cancel') ||
            code == 'auth_in_progress') {
          return _AuthOutcome.cancelled;
        }
        return _AuthOutcome.failed;
    }
  }

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
        return 'Authentication failed. Tap Unlock to try again.';
    }
  }

  // ── Logging ───────────────────────────────────────────────────────────────

  void _log(String tag, String message) =>
      dev.log('[$tag] $message', name: 'BiometricGate');

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    switch (_state) {
      case _LockState.initialising:
        // Plain background — no spinner flicker during the prefs read.
        return const Scaffold(backgroundColor: AppColors.bg);

      case _LockState.unlocked:
        return widget.child;

      case _LockState.locked:
      case _LockState.authenticating:
      case _LockState.error:
        return _LockScreen(
          state: _state,
          errorMessage: _errorMessage,
          onRetry: _promptAuth,
        );
    }
  }
}

// ── Lock Screen UI ────────────────────────────────────────────────────────────

class _LockScreen extends StatelessWidget {
  final _LockState state;
  final String? errorMessage;
  final VoidCallback onRetry;

  const _LockScreen({
    required this.state,
    this.errorMessage,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    final isAuthenticating = state == _LockState.authenticating;

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 44),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Logo with fallback shield icon if the asset is missing.
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
                if (isAuthenticating)
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
                  if (errorMessage != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 14),
                      child: Text(
                        errorMessage!,
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
