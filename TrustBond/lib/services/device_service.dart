import 'dart:io';
import 'dart:convert';
import 'dart:math';
import 'package:crypto/crypto.dart';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api_service.dart';

class DeviceService {
  static const String _deviceHashKey = 'device_hash';
  static const String _deviceIdKey = 'device_id';

  Future<String> getDeviceHash() async {
    final prefs = await SharedPreferences.getInstance();
    String? storedHash = prefs.getString(_deviceHashKey);
    
    if (storedHash != null) {
      return storedHash;
    }

    // Generate device hash from device info (anonymous)
    final deviceInfo = DeviceInfoPlugin();
    String deviceId = '';
    
    if (Platform.isAndroid) {
      final androidInfo = await deviceInfo.androidInfo;
      deviceId = androidInfo.id; // Unique device ID
    } else if (Platform.isIOS) {
      final iosInfo = await deviceInfo.iosInfo;
      deviceId = iosInfo.identifierForVendor ?? '';
    } else if (Platform.isWindows) {
      final windowsInfo = await deviceInfo.windowsInfo;
      deviceId = windowsInfo.deviceId;
    } else {
      // Fallback for other platforms
      deviceId = DateTime.now().millisecondsSinceEpoch.toString();
    }
    
    final bytes = utf8.encode(deviceId);
    final hash = sha256.convert(bytes);
    final hashString = hash.toString();
    
    await prefs.setString(_deviceHashKey, hashString);
    return hashString;
  }

  Future<String?> getDeviceId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_deviceIdKey);
  }

  Future<void> saveDeviceId(String deviceId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_deviceIdKey, deviceId);
  }

  /// Clear cached device identity (user must register again on next use).
  Future<void> clearLocalIdentity() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_deviceIdKey);
    await prefs.remove(_deviceHashKey);
  }

  /// Replaces the current device identity with a fresh random one.
  ///
  /// The old [device_hash] stays on the server linked to previous reports,
  /// but this app will never use that hash again — permanently severing
  /// the link so old reports can no longer be retrieved on this device.
  /// New reports submitted after calling this will use the new identity.
  Future<void> resetIdentity() async {
    final prefs = await SharedPreferences.getInstance();

    // Generate a cryptographically random 32-byte value and hash it.
    // This is deliberately NOT derived from hardware so it differs from
    // any previous identity.
    final rng = Random.secure();
    final randomBytes = List<int>.generate(32, (_) => rng.nextInt(256));
    final newHash = sha256.convert(randomBytes).toString();

    await prefs.setString(_deviceHashKey, newHash);
    await prefs.remove(_deviceIdKey); // will re-register on next report
  }

  /// Ensure a backend device_id exists and is cached locally.
  /// Returns null if registration could not be completed.
  Future<String?> ensureDeviceId({ApiService? apiService}) async {
    final existing = await getDeviceId();
    if (existing != null && existing.isNotEmpty) {
      return existing;
    }

    final hash = await getDeviceHash();
    if (hash.isEmpty) return null;

    final api = apiService ?? ApiService();
    final result = await api.registerDevice(hash);
    final id = result['device_id']?.toString();
    if (id == null || id.isEmpty) return null;

    await saveDeviceId(id);
    return id;
  }
}
