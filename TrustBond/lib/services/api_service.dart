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

  /// Fetch per-device profile stats for the mobile Profile screen.
  /// Uses the anonymous device_hash (legacy-compatible).
  Future<Map<String, dynamic>> getDeviceProfile(String deviceHash) async {
    final response = await _client
        .get(
          Uri.parse('${ApiConfig.devicesUrl}/profile/$deviceHash'),
          headers: _getHeaders,
        )
        .timeout(_timeout);

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }

    throw Exception('Failed to get device profile: ${response.statusCode}');
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
    String message = 'Failed to submit report';
    try {
      final err = jsonDecode(response.body);
      if (err is Map && err['detail'] != null) {
        message = err['detail'] is String
            ? err['detail'] as String
            : err['detail'].toString();
      }
    } catch (_) {}
    throw Exception('$message (HTTP ${response.statusCode})');
  }

  /// Delete a report (used for rollback if evidence upload fails).
  Future<void> deleteReport(String reportId, String deviceId) async {
    final uri = Uri.parse('${ApiConfig.reportsUrl}/$reportId').replace(
      queryParameters: {'device_id': deviceId},
    );
    final response = await _client.delete(uri, headers: _getHeaders).timeout(_timeout);
    if (response.statusCode != 204 && response.statusCode != 200) {
      throw Exception('Failed to delete/rollback report: ${response.statusCode}');
    }
  }

  /// Public locations browser for mobile Safety Map.
  /// locationType: sector | cell | village
  Future<List<dynamic>> getPublicLocations({
    String? locationType,
    int? parentId,
    int limit = 2000,
  }) async {
    final uri = Uri.parse('${ApiConfig.publicLocationsUrl}/').replace(
      queryParameters: {
        if (locationType != null) 'location_type': locationType,
        if (parentId != null) 'parent_id': parentId.toString(),
        'limit': limit.toString(),
      },
    );
    final response = await _client.get(uri, headers: _getHeaders).timeout(_timeout);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as List<dynamic>;
    }
    throw Exception('Failed to load locations: ${response.statusCode}');
  }

  /// Fetch polygon boundaries from backend as GeoJSON FeatureCollection.
  Future<Map<String, dynamic>> getPublicLocationsGeoJson({
    String locationType = 'village',
    int? parentId,
    int limit = 10000,
  }) async {
    final uri = Uri.parse(ApiConfig.publicLocationsGeoJsonUrl).replace(
      queryParameters: {
        'location_type': locationType,
        if (parentId != null) 'parent_id': parentId.toString(),
        'limit': limit.toString(),
      },
    );
    final response = await _client.get(uri, headers: _getHeaders).timeout(_timeout);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to load map polygons: ${response.statusCode}');
  }

  /// Fetch nearby AI-generated public safety alerts around user location.
  Future<List<dynamic>> getPublicAlerts({
    required double latitude,
    required double longitude,
    double radiusKm = 10.0,
    int limit = 20,
  }) async {
    final uri = Uri.parse('${ApiConfig.baseUrl}/api/v1/public/alerts').replace(
      queryParameters: {
        'latitude': latitude.toString(),
        'longitude': longitude.toString(),
        'radius_km': radiusKm.toString(),
        'limit': limit.toString(),
      },
    );

    final response = await _client
        .get(
          uri,
          headers: _getHeaders,
        )
        .timeout(_timeout);

    if (response.statusCode == 200) {
      final decoded = jsonDecode(response.body);
      if (decoded is List) {
        return decoded;
      }
      return <dynamic>[];
    }
    throw Exception('Failed to load public alerts: ${response.statusCode}');
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

  /// Submit a community confirmation vote on a report (real / false / unknown)
  Future<Map<String, dynamic>> submitCommunityVote(String reportId, String deviceId, String vote) async {
    final response = await _client.post(
      Uri.parse('${ApiConfig.reportsUrl}/$reportId/confirm'),
      headers: _jsonHeaders,
      body: jsonEncode({
        'device_id': deviceId,
        'vote': vote,
      }),
    ).timeout(_timeout);
    
    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    String message = 'Failed to submit vote (${response.statusCode})';
    try {
      final err = jsonDecode(response.body);
      if (err is Map && err['detail'] != null) {
        message = err['detail'].toString();
      }
    } catch (_) {}
    throw Exception(message);
  }

  /// Fetch nearby reports that the user can help confirm (community voting).
  /// Returns reports the backend considers eligible for confirmation.
  Future<List<dynamic>> getNearbyConfirmations({
    required String deviceId,
    required double latitude,
    required double longitude,
    int radiusMeters = 600,
    int limit = 10,
  }) async {
    final uri = Uri.parse('${ApiConfig.reportsUrl}/nearby-confirmations').replace(
      queryParameters: {
        'device_id': deviceId,
        'latitude': latitude.toString(),
        'longitude': longitude.toString(),
        'radius_meters': radiusMeters.toString(),
        'limit': limit.toString(),
      },
    );

    final response = await _client.get(uri, headers: _getHeaders).timeout(_timeout);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as List<dynamic>;
    }
    String message = 'Failed to load nearby confirmations (${response.statusCode})';
    try {
      final err = jsonDecode(response.body);
      if (err is Map && err['detail'] != null) {
        message = err['detail'].toString();
      }
    } catch (_) {}
    throw Exception(message);
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
