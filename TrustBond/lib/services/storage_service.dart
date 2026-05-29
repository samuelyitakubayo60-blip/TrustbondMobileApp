import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:local_auth/local_auth.dart';

import 'platform_service.dart';

/// Secure storage and biometric helpers (mobile only for biometrics).
class StorageService {
  static final StorageService _instance = StorageService._internal();
  factory StorageService() => _instance;
  StorageService._internal();

  final LocalAuthentication _localAuth = LocalAuthentication();

  void _log(String message) {
    if (kDebugMode) {
      debugPrint(message);
    }
  }

  /// Enable data encryption
  Future<void> enableEncryption() async {
    _log('Storage: Encryption enabled (mock implementation)');
  }

  /// Disable data encryption
  Future<void> disableEncryption() async {
    _log('Storage: Encryption disabled (mock implementation)');
  }

  /// Returns true if the device has any lock set (biometric, PIN, pattern, or password).
  Future<bool> isDeviceLockAvailable() async {
    if (!PlatformService.isMobile) return false;
    try {
      return await _localAuth.isDeviceSupported();
    } on PlatformException catch (e) {
      _log('Storage: device lock check failed: $e');
      return false;
    }
  }

  /// Check if biometric authentication is available on this device.
  Future<bool> isBiometricAvailable() async {
    if (!PlatformService.isMobile) return false;
    try {
      final supported = await _localAuth.isDeviceSupported();
      if (!supported) return false;
      final types = await _localAuth.getAvailableBiometrics();
      return types.isNotEmpty;
    } on PlatformException catch (e) {
      _log('Storage: biometric availability check failed: $e');
      return false;
    }
  }

  /// Authenticate using the device lock (fingerprint, face, PIN, pattern, password).
  /// Falls back to PIN/pattern/password if biometrics are not enrolled.
  Future<bool> authenticateWithBiometrics({
    String reason = 'Unlock TrustBond to continue',
  }) async {
    if (!PlatformService.isMobile) return false;
    try {
      final supported = await _localAuth.isDeviceSupported();
      if (!supported) return false;

      return await _localAuth.authenticate(
        localizedReason: reason,
        options: const AuthenticationOptions(
          biometricOnly: false,
          stickyAuth: true,
        ),
      );
    } on PlatformException catch (e) {
      _log('Storage: authentication failed: $e');
      return false;
    } catch (e) {
      _log('Storage: authentication failed: $e');
      return false;
    }
  }

  /// Enable secure storage
  Future<void> enableSecureStorage() async {
    _log('Storage: Secure storage enabled (mock implementation)');
  }

  /// Disable secure storage
  Future<void> disableSecureStorage() async {
    _log('Storage: Secure storage disabled (mock implementation)');
  }

  /// Enable auto backup
  Future<void> enableAutoBackup() async {
    _log('Storage: Auto backup enabled (mock implementation)');
  }

  /// Disable auto backup
  Future<void> disableAutoBackup() async {
    _log('Storage: Auto backup disabled (mock implementation)');
  }
}
