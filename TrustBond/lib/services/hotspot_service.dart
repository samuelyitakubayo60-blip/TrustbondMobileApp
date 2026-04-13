import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../config/api_config.dart';

class Hotspot {
  final String hotspotId;
  final double centerLat;
  final double centerLong;
  final String riskLevel;
  final int incidentCount;
  final int timeWindowHours;
  final double radiusMeters;
  final String? incidentTypeName;
  final DateTime detectedAt;

  Hotspot({
    required this.hotspotId,
    required this.centerLat,
    required this.centerLong,
    required this.riskLevel,
    required this.incidentCount,
    required this.timeWindowHours,
    required this.radiusMeters,
    this.incidentTypeName,
    required this.detectedAt,
  });

  factory Hotspot.fromJson(Map<String, dynamic> json) {
    return Hotspot(
      hotspotId: json['hotspot_id'].toString(),
      centerLat: double.parse(json['center_lat'].toString()),
      centerLong: double.parse(json['center_long'].toString()),
      riskLevel: json['risk_level'] as String,
      incidentCount: json['incident_count'] as int,
      timeWindowHours: json['time_window_hours'] as int,
      radiusMeters: double.parse(json['radius_meters'].toString()),
      incidentTypeName: json['incident_type_name'] as String?,
      detectedAt: DateTime.parse(json['detected_at']),
    );
  }

  String get riskEmoji {
    switch (riskLevel.toLowerCase()) {
      case 'high':
        return '🔴';
      case 'medium':
        return '🟡';
      case 'low':
        return '🟢';
      default:
        return '⚪';
    }
  }

  String get riskText {
    switch (riskLevel.toLowerCase()) {
      case 'high':
        return 'High Risk';
      case 'medium':
        return 'Medium Risk';
      case 'low':
        return 'Low Risk';
      default:
        return 'Unknown Risk';
    }
  }
}

class HotspotService {
  final String _baseUrl = ApiConfig.baseUrl;
  final http.Client _client = http.Client();
  static const String _allHotspotsCacheKey = 'tb_cache_public_hotspots_v1';

  Future<List<Hotspot>> getAllHotspots() async {
    try {
      final response = await _client.get(
        Uri.parse('$_baseUrl/public/hotspots'),
        headers: {'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 30));

      if (response.statusCode != 200 || response.body.isEmpty) {
        throw Exception('Failed to load hotspots: ${response.statusCode}');
      }

      final List<dynamic> data = json.decode(response.body);
      await _saveCache(data);
      return data
          .map((json) => Hotspot.fromJson(json as Map<String, dynamic>))
          .toList();
    } catch (_) {
      return _readCachedHotspots();
    }
  }

  Future<List<Hotspot>> getVillageHotspots(int sectorId) async {
    try {
      final response = await _client.get(
        Uri.parse('$_baseUrl/api/v1/public/hotspots'),
        headers: {'Content-Type': 'application/json'},
      );

      if (response.statusCode == 200) {
        final List<dynamic> data = json.decode(response.body);
        return data.map((json) => Hotspot.fromJson(json)).toList();
      } else {
        throw Exception('Failed to load village hotspots: ${response.statusCode}');
      }
    } catch (_) {
      return _readCachedHotspots();
    }
  }

  Future<List<Hotspot>> getCellHotspots({required int sectorId}) async {
    try {
      final response = await _client.get(
        Uri.parse('$_baseUrl/api/v1/public/hotspots'),
        headers: {'Content-Type': 'application/json'},
      );

      if (response.statusCode == 200) {
        final List<dynamic> data = json.decode(response.body);
        return data.map((json) => Hotspot.fromJson(json)).toList();
      } else {
        throw Exception('Failed to load cell hotspots: ${response.statusCode}');
      }
    } catch (_) {
      return _readCachedHotspots();
    }
  }

  Future<void> _saveCache(List<dynamic> data) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_allHotspotsCacheKey, jsonEncode(data));
  }

  Future<List<Hotspot>> _readCachedHotspots() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_allHotspotsCacheKey);
    if (raw == null || raw.isEmpty) {
      return <Hotspot>[];
    }

    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) {
        return <Hotspot>[];
      }
      return decoded
          .whereType<Map>()
          .map((json) => Hotspot.fromJson(Map<String, dynamic>.from(json)))
          .toList();
    } catch (_) {
      return <Hotspot>[];
    }
  }

  void dispose() {
    _client.close();
  }
}

