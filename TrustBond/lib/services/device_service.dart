import 'dart:io';
import 'dart:convert';
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
