import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:local_auth/local_auth.dart';
import 'package:local_auth/error_codes.dart' as auth_error;

import 'platform_service.dart';

/// Shared [local_auth] options for TrustBond app lock.
///
/// - [biometricOnly]: false — OS may use Face ID, Touch ID, fingerprint, iris,
///   or fall back to device PIN / pattern / password.
/// - [stickyAuth]: true — survive brief focus loss during a scan (Android).
/// - [sensitiveTransaction]: false — avoids an extra Android confirmation step
///   after face unlock (intended for payments, not app lock).
const appLockAuthOptions = AuthenticationOptions(
  biometricOnly: false,
  stickyAuth: true,
  sensitiveTransaction: false,
  useErrorDialogs: true,
);

/// Device capabilities for app-lock prompts and UI copy.
class DeviceAuthCapabilities {
  const DeviceAuthCapabilities({
    required this.deviceSupported,
    this.enrolledBiometrics = const [],
    this.probeError,
  });

  final bool deviceSupported;
  final List<BiometricType> enrolledBiometrics;
  final String? probeError;

  bool get hasFace => enrolledBiometrics.contains(BiometricType.face);

  bool get hasFingerprint =>
      enrolledBiometrics.contains(BiometricType.fingerprint);

  bool get hasIris => enrolledBiometrics.contains(BiometricType.iris);

  bool get hasClassBiometric => enrolledBiometrics.any(
        (t) => t == BiometricType.strong || t == BiometricType.weak,
      );

  bool get hasExplicitBiometric =>
      hasFace || hasFingerprint || hasIris || hasClassBiometric;

  /// Human-readable list for subtitles (Face ID, fingerprint, PIN, …).
  String get methodsShortLabel {
    final parts = <String>[];
    if (hasFace) parts.add('Face ID');
    if (hasFingerprint) parts.add('fingerprint');
    if (hasIris) parts.add('iris');
    if (parts.isEmpty && hasClassBiometric) {
      parts.add('face or fingerprint');
    }
    if (parts.isEmpty) {
      return 'PIN, pattern, or password';
    }
    return parts.join(', ');
  }

  String get unlockSubtitle {
    if (!deviceSupported) {
      return 'Set a device screen lock in system Settings.';
    }
    if (hasExplicitBiometric) {
      return 'Use $methodsShortLabel, or your device PIN.';
    }
    return 'Use your device PIN, pattern, or password.';
  }

  String localizedReason({String action = 'Unlock TrustBond'}) {
    if (!deviceSupported) return action;
    if (hasExplicitBiometric) {
      return '$action with $methodsShortLabel or your device PIN';
    }
    return '$action with your device PIN, pattern, or password';
  }

  IconData get lockIcon {
    if (hasFace) return Icons.face_rounded;
    if (hasFingerprint) return Icons.fingerprint_rounded;
    if (hasIris) return Icons.remove_red_eye_outlined;
    return Icons.lock_rounded;
  }

  bool get canAuthenticate => deviceSupported && probeError == null;
}

/// App-lock authentication via the device OS (face, fingerprint, PIN, …).
class AppLockAuth {
  AppLockAuth._();
  static final AppLockAuth instance = AppLockAuth._();

  final LocalAuthentication _localAuth = LocalAuthentication();

  void _log(String message) {
    if (kDebugMode) debugPrint('AppLockAuth: $message');
  }

  Future<DeviceAuthCapabilities> probe() async {
    if (!PlatformService.isMobile) {
      return const DeviceAuthCapabilities(
        deviceSupported: false,
        probeError: 'Not available on this platform.',
      );
    }

    try {
      final deviceSupported = await _localAuth.isDeviceSupported();
      if (!deviceSupported) {
        return const DeviceAuthCapabilities(
          deviceSupported: false,
          probeError:
              'This device does not support secure authentication. '
              'Enable a PIN or biometric in Settings.',
        );
      }

      List<BiometricType> enrolled = const [];
      try {
        enrolled = await _localAuth.getAvailableBiometrics();
        _log('enrolled=${enrolled.map((e) => e.name).join(", ")}');
      } on PlatformException catch (e) {
        // Non-fatal: on some Android builds face is available but not listed
        // until authenticate() is called — still allow PIN / OS picker.
        _log('getAvailableBiometrics failed (non-fatal): ${e.code}');
      }

      return DeviceAuthCapabilities(
        deviceSupported: true,
        enrolledBiometrics: enrolled,
      );
    } on PlatformException catch (e) {
      return DeviceAuthCapabilities(
        deviceSupported: false,
        probeError: friendlyError(e.code),
      );
    }
  }

  Future<bool> authenticate({String? localizedReason}) async {
    if (!PlatformService.isMobile) return false;

    final caps = await probe();
    if (!caps.canAuthenticate) return false;

    final reason =
        localizedReason ?? caps.localizedReason(action: 'Unlock TrustBond');

    try {
      return await _localAuth.authenticate(
        localizedReason: reason,
        options: appLockAuthOptions,
      );
    } on PlatformException catch (e) {
      _log('authenticate failed: ${e.code} ${e.message}');
      return false;
    } catch (e) {
      _log('authenticate failed: $e');
      return false;
    }
  }

  static String friendlyError(String code) {
    switch (code) {
      case auth_error.notAvailable:
        return 'Biometric authentication is not available on this device.';
      case auth_error.notEnrolled:
        return 'No biometrics enrolled. Add a fingerprint or face in Settings → Security.';
      case auth_error.lockedOut:
        return 'Too many failed attempts. Wait a moment and try again.';
      case auth_error.permanentlyLockedOut:
        return 'Biometrics locked out. Unlock with your device PIN first.';
      case auth_error.passcodeNotSet:
        return 'No screen lock set. Enable a PIN or biometric in device Settings.';
      case auth_error.otherOperatingSystem:
        return 'Authentication is not supported on this platform.';
      default:
        return 'Authentication failed. Tap Unlock to try again.';
    }
  }
}
