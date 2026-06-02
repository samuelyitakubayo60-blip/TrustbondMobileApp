import 'dart:async';
import 'dart:developer' as dev;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:local_auth/error_codes.dart' as auth_error;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/theme.dart';
import '../services/app_lock_auth.dart';

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
  timedOut,     // 90-second watchdog elapsed
  unavailable,  // no biometrics enrolled, no PIN set, hardware locked out
}

// ── BiometricGate ─────────────────────────────────────────────────────────────

/// Wraps any child widget and enforces the app-lock (biometric / device PIN)
/// when `biometric_auth` is `true` in SharedPreferences.
///
/// Lock trigger rules
/// ──────────────────
/// Auth is prompted in EXACTLY two situations:
///   1. App first launch  — [_init] locks and calls [_promptAuth] once.
///   2. Genuine background — the [_lockTimer] fires after [_lockDelay] and
///      sets [_pendingLockFromTimer] = true.  [_onResumed] reads this flag and
///      calls [_promptAuth] once, then clears the flag.
///
/// Everything else — post-auth biometric-Activity lifecycle events, brief OS
/// interruptions (volume bar, permission dialog, notification shade), and any
/// other transient focus loss — results in [_pendingLockFromTimer] being false
/// on resume, so [_onResumed] returns early without ever showing the prompt.
///
/// Loop prevention
/// ───────────────
/// • [_pendingLockFromTimer] is the single authoritative gate in [_onResumed].
///   It is only set inside the [_lockTimer] callback and cleared on the first
///   resume after the timer fires.  Post-auth resumed events see it as false
///   regardless of how long auth took or how many resumed events Android fires.
/// • [_unlockCooldown] in [_onBackground] prevents the lock timer from starting
///   within 3 s of a successful unlock (the biometric Activity fires [paused]
///   on some devices immediately after delivering the auth result).
/// • [_authGen] discards stale results from superseded auth attempts.
/// • [_state == authenticating] blocks [_onBackground] from starting the timer.
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
  /// [resumed] event where [_pendingLockFromTimer] is true.
  bool _lockEnabled = false;

  // ── Timing guard: post-unlock cooldown ────────────────────────────────────

  /// Stamped on every successful unlock.  [_onBackground] skips starting the
  /// lock timer within [_unlockCooldown] — the biometric Activity fires [paused]
  /// on some devices immediately after delivering the auth result.
  DateTime? _lastUnlockedAt;
  static const _unlockCooldown = Duration(seconds: 3);

  // ── Background lock timer ─────────────────────────────────────────────────

  /// Timer started by [_onBackground].  If [_onResumed] fires before it expires
  /// the app was briefly interrupted (< [_lockDelay]) and stays unlocked.
  Timer? _lockTimer;
  static const _lockDelay = Duration(seconds: 5);

  /// Set to true ONLY inside the [_lockTimer] callback (genuine background of
  /// [_lockDelay]+).  Cleared by [_onResumed] on the first resume after the
  /// timer fires.  This is the single gate that decides whether [_onResumed]
  /// should prompt authentication.  Post-auth resumed events never set this flag
  /// and therefore never trigger a new prompt, regardless of timing.
  bool _pendingLockFromTimer = false;

  /// Set to true once [_init] has fully completed (prefs read AND first auth
  /// attempt launched or skipped).  Guards [_onResumed] from acting on any
  /// [resumed] events that Android fires during [initState] before [_init]
  /// finishes — which would race against the initial [_promptAuth] call.
  bool _initComplete = false;

  // ── Concurrency guard ─────────────────────────────────────────────────────

  /// Incremented each time a new auth attempt starts.  When the future
  /// resolves, if [_authGen] no longer matches the captured generation the
  /// result is from a superseded attempt and is silently discarded.
  int _authGen = 0;

  final _appLock = AppLockAuth.instance;

  /// Cached after [_init] for lock-screen copy (face / fingerprint / PIN).
  DeviceAuthCapabilities _authCaps = const DeviceAuthCapabilities(
    deviceSupported: true,
  );

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
    _authCaps = await _appLock.probe();
    _log('init', 'lockEnabled=$_lockEnabled caps=${_authCaps.methodsShortLabel}');

    if (_lockEnabled) {
      _transition(_LockState.locked);
      _initComplete = true;
      await _promptAuth();
    } else {
      _transition(_LockState.unlocked);
      _initComplete = true;
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
  /// background of [_lockDelay] or more causes [_pendingLockFromTimer] to be
  /// set and the app to lock.
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
        // Set the flag BEFORE transitioning so _onResumed knows this lock
        // was triggered by a genuine background, not a post-auth event.
        _pendingLockFromTimer = true;
        _transition(_LockState.locked);
      }
    });
  }

  // ── Resumed ───────────────────────────────────────────────────────────────

  Future<void> _onResumed() async {
    // Ignore resumed events that fire during initState before _init() has
    // finished reading prefs and launching the initial auth prompt.
    if (!_initComplete) {
      _log('resumed', 'init not complete — skipped');
      return;
    }

    // Cancel any pending lock timer and check whether it was still ticking.
    // • Timer still active  → app was backgrounded for less than [_lockDelay]
    //                          (brief interruption). Cancel and stay unlocked.
    // • Timer already fired → [_pendingLockFromTimer] was set; fall through.
    // • Timer is null       → no backgrounding started (launch, post-auth, etc.)
    final wasTimerActive = _lockTimer?.isActive ?? false;
    _lockTimer?.cancel();
    _lockTimer = null;

    if (wasTimerActive) {
      // Brief interruption — timer was still counting down.
      // The app was backgrounded for less than [_lockDelay]; stay unlocked.
      _log('resumed', 'brief interruption — lock timer cancelled, no re-lock');
      return;
    }

    // ── KEY GATE ──────────────────────────────────────────────────────────
    // Only proceed if [_lockTimer] actually fired.  This is the single check
    // that prevents post-auth biometric-Activity lifecycle events, initial
    // launch resumed events, and any other non-background resumed events from
    // triggering an auth prompt.
    //
    // [_pendingLockFromTimer] is set exclusively inside the [_lockTimer]
    // callback — meaning the app was genuinely in the background for at least
    // [_lockDelay] seconds.  Every other code path leaves it false.
    if (!_pendingLockFromTimer) {
      _log('resumed', 'no genuine background lock pending — skipped');
      return;
    }
    _pendingLockFromTimer = false;

    // Refresh cached setting — user may have toggled biometric lock in the
    // Settings screen while the app was backgrounded.
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;

    final previous = _lockEnabled;
    _lockEnabled = prefs.getBool('biometric_auth') ?? false;
    if (previous != _lockEnabled) {
      _log('resumed', 'lockEnabled changed: $previous → $_lockEnabled');
    }

    // Lock was disabled while app was in background — unlock immediately,
    // no auth required.
    if (!_lockEnabled) {
      if (_isLocked) {
        _log('resumed', 'lock disabled — unlocking without prompt');
        _transition(_LockState.unlocked);
      }
      return;
    }

    // Nothing to do if already unlocked or mid-authentication.
    if (!_isLocked || _state == _LockState.authenticating) return;

    _log('resumed', 'locked after genuine background — prompting');
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
    _log('auth', 'gen=$gen starting dialog');

    _AuthOutcome outcome = _AuthOutcome.failed;
    String? errorMessage;
    bool timedOut = false;

    final reason = _authCaps.localizedReason(action: 'Unlock TrustBond');

    try {
      final result = await _appLock
          .authenticate(localizedReason: reason)
          .timeout(
        // 90 s — must be longer than any realistic biometric scan + PIN entry.
        // stickyAuth:true keeps the native dialog alive across brief focus losses,
        // so the Dart timeout must not race against the system's own patience.
        // A 30 s Dart timeout fired before the user finished typing a long PIN,
        // discarding a valid auth result via _authGen mismatch → re-lock loop.
        const Duration(seconds: 90),
        onTimeout: () {
          timedOut = true;
          _log('auth', 'gen=$gen timed out after 90 s');
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
      errorMessage = AppLockAuth.friendlyError(e.code);
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
    _authCaps = await _appLock.probe();
    _log(
      'availability',
      'supported=${_authCaps.deviceSupported} methods=${_authCaps.methodsShortLabel}',
    );
    if (!_authCaps.canAuthenticate) {
      return (
        available: false,
        reason: _authCaps.probeError ??
            'Enable Face ID, fingerprint, or a device PIN in Settings.',
      );
    }
    return (available: true, reason: null);
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
          authCaps: _authCaps,
          onRetry: _promptAuth,
        );
    }
  }
}

// ── Lock Screen UI ────────────────────────────────────────────────────────────

class _LockScreen extends StatelessWidget {
  final _LockState state;
  final String? errorMessage;
  final DeviceAuthCapabilities authCaps;
  final VoidCallback onRetry;

  const _LockScreen({
    required this.state,
    this.errorMessage,
    required this.authCaps,
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
                      errorBuilder: (_, _, _) => Container(
                        width: 80,
                        height: 80,
                        decoration: BoxDecoration(
                          color: AppColors.accent.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(22),
                        ),
                        child: Icon(
                          authCaps.lockIcon,
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
                Text(
                  authCaps.unlockSubtitle,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 13, color: AppColors.muted),
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
                      icon: const Icon(Icons.lock_open_rounded, size: 20),
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
