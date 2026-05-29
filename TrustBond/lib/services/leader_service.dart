import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import '../config/api_config.dart';
import 'app_refresh_bus.dart';

class LeaderService {
  static final LeaderService _instance = LeaderService._internal();
  factory LeaderService() => _instance;
  LeaderService._internal();

  final http.Client _client = http.Client();
  static const Duration _timeout = Duration(seconds: 60);
  static const _storage = FlutterSecureStorage();
  static const _tokenKey = 'tb_leader_access_token';

  String _parseErrorMessage(http.Response res, String fallback) {
    try {
      final decoded = jsonDecode(res.body);
      if (decoded is Map) {
        final detail = decoded['detail'];
        if (detail is String && detail.trim().isNotEmpty) {
          return detail.trim();
        }
        if (detail is List && detail.isNotEmpty) {
          final first = detail.first;
          if (first is Map && first['msg'] != null) {
            return first['msg'].toString();
          }
        }
        if (decoded['message'] != null) {
          return decoded['message'].toString();
        }
      }
    } catch (_) {}
    final body = res.body.trim();
    if (body.isNotEmpty && body.length < 300) return body;
    return fallback;
  }

  Future<String?> getToken() => _storage.read(key: _tokenKey);

  /// Bearer token for report submit when a leader session exists.
  Future<String?> getAccessTokenForSubmission() async {
    final token = await getToken();
    if (token == null || token.trim().isEmpty) return null;
    return token.trim();
  }

  /// True when a stored token validates against /me.
  Future<bool> isSessionActive() async {
    final token = await getToken();
    if (token == null || token.trim().isEmpty) return false;
    try {
      await me();
      return true;
    } catch (_) {
      await logout();
      return false;
    }
  }

  Future<void> logout() async {
    await _storage.delete(key: _tokenKey);
    AppRefreshBus.notify('leader_session');
  }

  Future<void> login({required String email, required String password}) async {
    final res = await _client
        .post(
          Uri.parse('${ApiConfig.leaderAuthUrl}/login'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'email': email.trim(), 'password': password}),
        )
        .timeout(_timeout);

    if (res.statusCode != 200) {
      throw Exception(
        _parseErrorMessage(res, 'Login failed (HTTP ${res.statusCode})'),
      );
    }

    final decoded = jsonDecode(res.body) as Map<String, dynamic>;
    final token = decoded['access_token']?.toString();
    if (token == null || token.isEmpty) {
      throw Exception('Login failed: token missing');
    }
    await _storage.write(key: _tokenKey, value: token);
    AppRefreshBus.notify('leader_session');
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
      throw Exception(
        _parseErrorMessage(
          res,
          'Failed to request login code (HTTP ${res.statusCode})',
        ),
      );
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
      throw Exception(
        _parseErrorMessage(
          res,
          'Failed to request login code (HTTP ${res.statusCode})',
        ),
      );
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
      throw Exception(
        _parseErrorMessage(
          res,
          'Failed to verify login code (HTTP ${res.statusCode})',
        ),
      );
    }

    final decoded = jsonDecode(res.body) as Map<String, dynamic>;
    final token = decoded['access_token']?.toString();
    if (token == null || token.isEmpty) {
      throw Exception('Login failed: token missing');
    }
    await _storage.write(key: _tokenKey, value: token);
    AppRefreshBus.notify('leader_session');
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
      throw Exception(
        _parseErrorMessage(
          res,
          'Failed to request setup code (HTTP ${res.statusCode})',
        ),
      );
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
      throw Exception(
        _parseErrorMessage(
          res,
          'Failed to set password (HTTP ${res.statusCode})',
        ),
      );
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

  Future<Map<String, dynamic>> getReport(String reportId) async {
    final token = await getToken();
    if (token == null || token.isEmpty) {
      throw Exception('Not logged in');
    }
    final res = await _client
        .get(
          Uri.parse('${ApiConfig.leaderUrl}/reports/$reportId'),
          headers: {'Authorization': 'Bearer $token'},
        )
        .timeout(_timeout);
    if (res.statusCode != 200) {
      throw Exception('Failed to load report (HTTP ${res.statusCode})');
    }
    return jsonDecode(res.body) as Map<String, dynamic>;
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
