import 'package:flutter/services.dart';

/// Mock storage service for cross-platform compatibility
class StorageService {
  static final StorageService _instance = StorageService._internal();
  factory StorageService() => _instance;
  StorageService._internal();

  /// Enable data encryption
  Future<void> enableEncryption() async {
    print('Storage: Encryption enabled (mock implementation)');
  }

  /// Disable data encryption
  Future<void> disableEncryption() async {
    print('Storage: Encryption disabled (mock implementation)');
  }

  /// Check if biometric authentication is available
  Future<bool> isBiometricAvailable() async {
    // Mock implementation - always return false on desktop
    return false;
  }

  /// Authenticate with biometrics
  Future<bool> authenticateWithBiometrics() async {
    print('Storage: Biometric authentication attempted (mock implementation)');
    return false;
  }

  /// Enable secure storage
  Future<void> enableSecureStorage() async {
    print('Storage: Secure storage enabled (mock implementation)');
  }

  /// Disable secure storage
  Future<void> disableSecureStorage() async {
    print('Storage: Secure storage disabled (mock implementation)');
  }

  /// Enable auto backup
  Future<void> enableAutoBackup() async {
    print('Storage: Auto backup enabled (mock implementation)');
  }

  /// Disable auto backup
  Future<void> disableAutoBackup() async {
    print('Storage: Auto backup disabled (mock implementation)');
  }
}
