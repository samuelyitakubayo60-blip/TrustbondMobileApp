import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import '../config/api_config.dart';

class LeaderService {
  static final LeaderService _instance = LeaderService._internal();
  factory LeaderService() => _instance;
  LeaderService._internal();

  final http.Client _client = http.Client();
  static const Duration _timeout = Duration(seconds: 60);
  static const _storage = FlutterSecureStorage();
  static const _tokenKey = 'tb_leader_access_token';

  Future<String?> getToken() => _storage.read(key: _tokenKey);

  Future<void> logout() => _storage.delete(key: _tokenKey);

  Future<void> login({required String email, required String password}) async {
    final res = await _client
        .post(
          Uri.parse('${ApiConfig.leaderAuthUrl}/login'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'email': email.trim(), 'password': password}),
        )
        .timeout(_timeout);

    if (res.statusCode != 200) {
      String msg = 'Login failed (HTTP ${res.statusCode})';
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map && decoded['detail'] != null) {
          msg = decoded['detail'].toString();
        }
      } catch (_) {}
      throw Exception(msg);
    }

    final decoded = jsonDecode(res.body) as Map<String, dynamic>;
    final token = decoded['access_token']?.toString();
    if (token == null || token.isEmpty) {
      throw Exception('Login failed: token missing');
    }
    await _storage.write(key: _tokenKey, value: token);
  }

  Future<void> requestLoginCode({required String email}) async {
    final res = await _client
        .post(
          Uri.parse('${ApiConfig.leaderAuthUrl}/request-login-code'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'email': email.trim()}),
        )
        .timeout(_timeout);
    if (res.statusCode != 200) {
      String msg = 'Failed to request login code (HTTP ${res.statusCode})';
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map && decoded['detail'] != null) {
          msg = decoded['detail'].toString();
        }
      } catch (_) {}
      throw Exception(msg);
    }
  }

  Future<int?> requestLoginCodeWithRetryAfter({required String email}) async {
    final res = await _client
        .post(
          Uri.parse('${ApiConfig.leaderAuthUrl}/request-login-code'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'email': email.trim()}),
        )
        .timeout(_timeout);
    if (res.statusCode != 200) {
      String msg = 'Failed to request login code (HTTP ${res.statusCode})';
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map && decoded['detail'] != null) {
          msg = decoded['detail'].toString();
        }
      } catch (_) {}
      throw Exception(msg);
    }
    try {
      final decoded = jsonDecode(res.body);
      if (decoded is Map && decoded['retry_after_seconds'] != null) {
        final value = decoded['retry_after_seconds'];
        if (value is num) return value.toInt();
      }
    } catch (_) {}
    return null;
  }

  Future<void> verifyLoginCode({
    required String email,
    required String code,
  }) async {
    final res = await _client
        .post(
          Uri.parse('${ApiConfig.leaderAuthUrl}/verify-login-code'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'email': email.trim(),
            'code': code.trim(),
          }),
        )
        .timeout(_timeout);
    if (res.statusCode != 200) {
      String msg = 'Failed to verify login code (HTTP ${res.statusCode})';
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map && decoded['detail'] != null) {
          msg = decoded['detail'].toString();
        }
      } catch (_) {}
      throw Exception(msg);
    }

    final decoded = jsonDecode(res.body) as Map<String, dynamic>;
    final token = decoded['access_token']?.toString();
    if (token == null || token.isEmpty) {
      throw Exception('Login failed: token missing');
    }
    await _storage.write(key: _tokenKey, value: token);
  }

  Future<void> requestSetupCode({required String email}) async {
    final res = await _client
        .post(
          Uri.parse('${ApiConfig.leaderAuthUrl}/request-setup-code'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'email': email.trim()}),
        )
        .timeout(_timeout);
    if (res.statusCode != 200) {
      String msg = 'Failed to request setup code (HTTP ${res.statusCode})';
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map && decoded['detail'] != null) {
          msg = decoded['detail'].toString();
        }
      } catch (_) {}
      throw Exception(msg);
    }
  }

  Future<void> setPassword({
    required String email,
    required String code,
    required String newPassword,
  }) async {
    final res = await _client
        .post(
          Uri.parse('${ApiConfig.leaderAuthUrl}/set-password'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'email': email.trim(),
            'code': code.trim(),
            'new_password': newPassword,
          }),
        )
        .timeout(_timeout);
    if (res.statusCode != 200) {
      String msg = 'Failed to set password (HTTP ${res.statusCode})';
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map && decoded['detail'] != null) {
          msg = decoded['detail'].toString();
        }
      } catch (_) {}
      throw Exception(msg);
    }
  }

  Future<void> registerFcmToken({required String fcmToken}) async {
    final token = await getToken();
    if (token == null || token.isEmpty) {
      throw Exception('Not logged in');
    }
    final res = await _client
        .post(
          Uri.parse('${ApiConfig.leaderAuthUrl}/register-fcm-token'),
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer $token',
          },
          body: jsonEncode({'fcm_token': fcmToken}),
        )
        .timeout(_timeout);
    if (res.statusCode != 200) {
      String msg = 'Failed to register push token (HTTP ${res.statusCode})';
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map && decoded['detail'] != null) {
          msg = decoded['detail'].toString();
        }
      } catch (_) {}
      throw Exception(msg);
    }
  }

  Future<Map<String, dynamic>> me() async {
    final token = await getToken();
    if (token == null || token.isEmpty) {
      throw Exception('Not logged in');
    }
    final res = await _client
        .get(
          Uri.parse('${ApiConfig.leaderAuthUrl}/me'),
          headers: {'Authorization': 'Bearer $token'},
        )
        .timeout(_timeout);

    if (res.statusCode != 200) {
      throw Exception('Failed to load profile (HTTP ${res.statusCode})');
    }
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<List<dynamic>> listReports({bool onlyPending = true}) async {
    final token = await getToken();
    if (token == null || token.isEmpty) {
      throw Exception('Not logged in');
    }
    final uri = Uri.parse('${ApiConfig.leaderUrl}/reports').replace(
      queryParameters: {'only_pending': onlyPending.toString()},
    );
    final res = await _client
        .get(
          uri,
          headers: {'Authorization': 'Bearer $token'},
        )
        .timeout(_timeout);
    if (res.statusCode != 200) {
      throw Exception('Failed to load reports (HTTP ${res.statusCode})');
    }
    final decoded = jsonDecode(res.body) as Map<String, dynamic>;
    return (decoded['items'] as List<dynamic>? ?? <dynamic>[]);
  }

  Future<void> verifyReport({
    required String reportId,
    required String decision,
    String? note,
  }) async {
    final token = await getToken();
    if (token == null || token.isEmpty) {
      throw Exception('Not logged in');
    }
    final res = await _client
        .post(
          Uri.parse('${ApiConfig.leaderUrl}/reports/$reportId/verify'),
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer $token',
          },
          body: jsonEncode({'decision': decision, 'note': note}),
        )
        .timeout(_timeout);
    if (res.statusCode != 200) {
      String msg = 'Failed (HTTP ${res.statusCode})';
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map && decoded['detail'] != null) {
          msg = decoded['detail'].toString();
        }
      } catch (_) {}
      throw Exception(msg);
    }
  }
}
