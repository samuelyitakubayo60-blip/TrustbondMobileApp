import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';
import 'offline_database_service.dart';

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
  final OfflineDatabaseService _db = OfflineDatabaseService();

  Future<List<Hotspot>> getAllHotspots() async {
    try {
      final baseUrl = ApiConfig.baseUrl;
      final url = '$baseUrl/public/hotspots';
      
      print('🔍 DEBUG: === HOTSPOT API DEBUG ===');
      print('🔍 DEBUG: Base URL: "$baseUrl"');
      print('🔍 DEBUG: Full URL: "$url"');
      print('🔍 DEBUG: Making HTTP GET request...');
      
      final response = await _client.get(
        Uri.parse(url),
        headers: {'Content-Type': 'application/json'},
      ).timeout(
        const Duration(seconds: 30),
        onTimeout: () {
          print('🔍 DEBUG: Request timed out after 30 seconds');
          throw Exception('Request timeout');
        },
      );

      print('🔍 DEBUG: Response status: ${response.statusCode}');
      print('🔍 DEBUG: Response body: "${response.body}"');
      print('🔍 DEBUG: Response headers: ${response.headers}');

      if (response.statusCode == 200) {
        if (response.body.isEmpty) {
          print('🔍 DEBUG: Empty response body');
          throw Exception('Empty response from server');
        }
        
        try {
          final List<dynamic> data = json.decode(response.body);
          print('🔍 DEBUG: JSON decoded successfully, got ${data.length} items');
          
          final hotspots = data.map((json) {
            print('🔍 DEBUG: Parsing hotspot: $json');
            return Hotspot.fromJson(json);
          }).toList();
          
          print('🔍 DEBUG: Successfully parsed ${hotspots.length} hotspots');
          
          // Cache hotspots for offline use
          try {
            await _db.cacheHotspots(data.cast<Map<String, dynamic>>());
            print('🔍 DEBUG: Hotspots cached for offline use');
          } catch (e) {
            print('🔍 DEBUG: Failed to cache hotspots: $e');
            // Continue even if caching fails
          }
          
          return hotspots;
        } catch (e) {
          print('🔍 DEBUG: JSON parsing error: $e');
          print('🔍 DEBUG: Response was: "${response.body}"');
          throw Exception('Failed to parse JSON: $e');
        }
      } else {
        print('🔍 DEBUG: HTTP error ${response.statusCode}: ${response.reasonPhrase}');
        print('🔍 DEBUG: Error body: ${response.body}');
        throw Exception('HTTP ${response.statusCode}: ${response.reasonPhrase}');
      }
    } catch (e) {
      print('🔍 DEBUG: Exception in getAllHotspots: $e');
      print('🔍 DEBUG: Exception type: ${e.runtimeType}');
      print('🔍 DEBUG: Trying offline cache...');

      // Try to get hotspots from offline cache
      try {
        final cachedHotspots = await _db.getCachedHotspots();
        if (cachedHotspots.isNotEmpty) {
          print('🔍 DEBUG: Found ${cachedHotspots.length} hotspots in offline cache');
          return cachedHotspots.map((json) => Hotspot.fromJson(json)).toList();
        }
      } catch (cacheError) {
        print('🔍 DEBUG: Offline cache also failed: $cacheError');
      }

      // Return empty if both API and cache fail
      return <Hotspot>[];
    }
  }

  Future<List<Hotspot>> getVillageHotspots(int sectorId) async {
    try {
      print('🔍 DEBUG: Fetching village hotspots for sector $sectorId');
      
      final response = await _client.get(
        Uri.parse('$_baseUrl/api/v1/public/hotspots'),
        headers: {'Content-Type': 'application/json'},
      );

      print('🔍 DEBUG: Village Hotspot API Status: ${response.statusCode}');
      print('🔍 DEBUG: Village Hotspot API Response: ${response.body}');

      if (response.statusCode == 200) {
        final List<dynamic> data = json.decode(response.body);
        final hotspots = data.map((json) => Hotspot.fromJson(json)).toList();
        print('🔍 DEBUG: Parsed ${hotspots.length} village hotspots for sector $sectorId');
        return hotspots;
      } else {
        print('🔍 DEBUG: Village Hotspot API Error: ${response.statusCode}');
        throw Exception('Failed to load village hotspots: ${response.statusCode}');
      }
    } catch (e) {
      print('🔍 DEBUG: Village Hotspot Service Exception: $e');
      rethrow;
    }
  }

  Future<List<Hotspot>> getCellHotspots({required int sectorId}) async {
    try {
      print('🔍 DEBUG: Fetching cell hotspots for sector $sectorId');
      
      final response = await _client.get(
        Uri.parse('$_baseUrl/api/v1/public/hotspots'),
        headers: {'Content-Type': 'application/json'},
      );

      print('🔍 DEBUG: Cell Hotspot API Status: ${response.statusCode}');
      print('🔍 DEBUG: Cell Hotspot API Response: ${response.body}');

      if (response.statusCode == 200) {
        final List<dynamic> data = json.decode(response.body);
        final hotspots = data.map((json) => Hotspot.fromJson(json)).toList();
        print('🔍 DEBUG: Parsed ${hotspots.length} cell hotspots for sector $sectorId');
        return hotspots;
      } else {
        print('🔍 DEBUG: Cell Hotspot API Error: ${response.statusCode}');
        throw Exception('Failed to load cell hotspots: ${response.statusCode}');
      }
    } catch (e) {
      print('🔍 DEBUG: Cell Hotspot Service Exception: $e');
      rethrow;
    }
  }

  void dispose() {
    _client.close();
  }
}
