import 'package:flutter/foundation.dart';

import 'app_lock_auth.dart';
import 'platform_service.dart';

/// Secure storage and biometric helpers (mobile only for biometrics).
class StorageService {
  static final StorageService _instance = StorageService._internal();
  factory StorageService() => _instance;
  StorageService._internal();

  final _appLock = AppLockAuth.instance;

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
    final caps = await _appLock.probe();
    return caps.deviceSupported;
  }

  /// True when the device reports enrolled biometrics (face, fingerprint, iris, …).
  Future<bool> isBiometricAvailable() async {
    if (!PlatformService.isMobile) return false;
    final caps = await _appLock.probe();
    return caps.deviceSupported && caps.hasExplicitBiometric;
  }

  /// Device auth summary for settings / lock screen copy.
  Future<DeviceAuthCapabilities> deviceAuthCapabilities() => _appLock.probe();

  /// Authenticate with Face ID, Touch ID, fingerprint, iris, or device PIN.
  Future<bool> authenticateWithBiometrics({
    String reason = 'Unlock TrustBond to continue',
  }) async {
    if (!PlatformService.isMobile) return false;
    return _appLock.authenticate(localizedReason: reason);
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
