import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';

class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  final http.Client _client = http.Client();
  static const Duration _timeout = Duration(seconds: 60);

  /// Common headers for API requests.
  static const Map<String, String> _jsonHeaders = {
    'Content-Type': 'application/json',
  };
  static const Map<String, String> _getHeaders = {};

  Future<Map<String, dynamic>> registerDevice(String deviceHash) async {
    final response = await _client.post(
      Uri.parse('${ApiConfig.devicesUrl}/register'),
      headers: _jsonHeaders,
      body: jsonEncode({'device_hash': deviceHash}),
    ).timeout(_timeout);
    
    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    throw Exception('Failed to register device: ${response.statusCode}');
  }

  Future<List<dynamic>> getIncidentTypes() async {
    final response = await _client.get(
      Uri.parse('${ApiConfig.incidentTypesUrl}/'),
      headers: _getHeaders,
    ).timeout(_timeout);
    
    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    throw Exception('Failed to get incident types: ${response.statusCode}');
  }

  /// List reports for the given device (my reports).
  Future<List<dynamic>> getMyReports(String deviceId) async {
    final uri = Uri.parse('${ApiConfig.reportsUrl}/').replace(
      queryParameters: {'device_id': deviceId},
    );
    final response = await _client.get(uri, headers: _getHeaders).timeout(_timeout);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as List<dynamic>;
    }
    throw Exception('Failed to get my reports: ${response.statusCode}');
  }

  /// Get a single report; deviceId must match the report owner.
  Future<Map<String, dynamic>> getReport(String reportId, String deviceId) async {
    final uri = Uri.parse('${ApiConfig.reportsUrl}/$reportId').replace(
      queryParameters: {'device_id': deviceId},
    );
    final response = await _client.get(uri, headers: _getHeaders).timeout(_timeout);
    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    throw Exception('Failed to get report: ${response.statusCode}');
  }

  Future<Map<String, dynamic>> submitReport(Map<String, dynamic> reportData) async {
    final response = await _client.post(
      Uri.parse('${ApiConfig.reportsUrl}/'),
      headers: _jsonHeaders,
      body: jsonEncode(reportData),
    ).timeout(_timeout);
    
    if (response.statusCode == 200 || response.statusCode == 201) {
      return jsonDecode(response.body);
    }

    // Parse the actual error detail from the backend
    String message = 'Failed to submit report (${response.statusCode})';
    try {
      final err = jsonDecode(response.body);
      if (err is Map && err['detail'] != null) {
        message = err['detail'] is String
            ? err['detail'] as String
            : err['detail'].toString();
      }
    } catch (_) {}
    throw Exception(message);
  }

  /// Upload evidence to an existing report (e.g. add evidence later). deviceId is required.
  Future<Map<String, dynamic>> uploadEvidence(
    String reportId,
    String deviceId,
    String filePath, {
    double? mediaLatitude,
    double? mediaLongitude,
    DateTime? capturedAt,
    bool isLiveCapture = false,
  }) async {
    var request = http.MultipartRequest(
      'POST',
      Uri.parse('${ApiConfig.reportsUrl}/$reportId/evidence'),
    );
    request.headers.addAll(_getHeaders);
    request.fields['device_id'] = deviceId.trim();
    request.files.add(await http.MultipartFile.fromPath('file', filePath));

    if (mediaLatitude != null) {
      request.fields['media_latitude'] = mediaLatitude.toString();
    }
    if (mediaLongitude != null) {
      request.fields['media_longitude'] = mediaLongitude.toString();
    }
    if (capturedAt != null) {
      request.fields['captured_at'] = capturedAt.toIso8601String();
    }
    request.fields['is_live_capture'] = isLiveCapture.toString();

    final response = await _client.send(request);
    final responseBody = await response.stream.bytesToString();
    if (response.statusCode == 200) {
      return jsonDecode(responseBody);
    }
    String message = 'Failed to upload evidence';
    try {
      final err = jsonDecode(responseBody) as Map<String, dynamic>;
      if (err['detail'] != null) {
        message = err['detail'] is String
            ? err['detail'] as String
            : (err['detail'] as List).isNotEmpty
                ? (err['detail'] as List).first.toString()
                : message;
      }
    } catch (_) {}
    throw EvidenceUploadException(message, response.statusCode);
  }
}

/// Custom exception for evidence upload failures with status code info.
class EvidenceUploadException implements Exception {
  final String message;
  final int statusCode;
  EvidenceUploadException(this.message, this.statusCode);

  @override
  String toString() => message;
}
