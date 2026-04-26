import 'package:flutter/foundation.dart';

/// Mock storage service for cross-platform compatibility
class StorageService {
  static final StorageService _instance = StorageService._internal();
  factory StorageService() => _instance;
  StorageService._internal();

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

  /// Check if biometric authentication is available
  Future<bool> isBiometricAvailable() async {
    // Mock implementation - always return false on desktop
    return false;
  }

  /// Authenticate with biometrics
  Future<bool> authenticateWithBiometrics() async {
    _log('Storage: Biometric authentication attempted (mock implementation)');
    return false;
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
