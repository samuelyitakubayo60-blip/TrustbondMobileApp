import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
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
  final String? citizenAdvisory;

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
    this.citizenAdvisory,
  });

  factory Hotspot.fromJson(Map<String, dynamic> json) {
    final prediction = json['prediction'] as Map<String, dynamic>?;
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
      citizenAdvisory: prediction?['citizen_advisory'] as String?,
    );
  }

  String get riskEmoji {
    switch (riskLevel.toLowerCase()) {
      case 'critical':
      case 'active':
      case 'high':
        return '🔴';
      case 'emerging':
      case 'medium':
        return '🟡';
      case 'low_activity':
      case 'low':
        return '🟢';
      default:
        return '⚪';
    }
  }

  String get riskText {
    switch (riskLevel.toLowerCase()) {
      case 'critical':
        return 'Critical Risk';
      case 'active':
      case 'high':
        return 'High Risk';
      case 'emerging':
      case 'medium':
        return 'Medium Risk';
      case 'low_activity':
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

  Future<List<Hotspot>> getAllHotspots({
    int? timeWindowHours,
    double? lat,
    double? lon,
    int? radiusMeters,
  }) async {
    try {
      final uri = Uri.parse('$_baseUrl/public/hotspots').replace(
        queryParameters: {
          if (timeWindowHours != null)
            'time_window_hours': timeWindowHours.toString(),
          if (lat != null && lon != null) 'lat': lat.toString(),
          if (lat != null && lon != null) 'lon': lon.toString(),
          if (lat != null && lon != null && radiusMeters != null)
            'radius_meters': radiusMeters.toString(),
        },
      );
      
      debugPrint('Loading hotspots from: $uri');
      
      final response = await _client.get(
        uri,
        headers: {'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 30));

      debugPrint('Hotspots response status: ${response.statusCode}');
      debugPrint('Hotspots response body: ${response.body}');

      if (response.statusCode != 200) {
        throw Exception('Failed to load hotspots: ${response.statusCode} - ${response.body}');
      }

      if (response.body.isEmpty) {
        debugPrint('Empty response body for hotspots');
        return <Hotspot>[];
      }

      final List<dynamic> data = json.decode(response.body);
      debugPrint('Parsed ${data.length} hotspots');
      
      return data
          .map((json) => Hotspot.fromJson(json as Map<String, dynamic>))
          .toList();
    } catch (e) {
      debugPrint('Error loading hotspots: $e');
      return <Hotspot>[];
    }
  }

  Future<List<Hotspot>> getNearbyHotspots({
    required double lat,
    required double lon,
    int radiusMeters = 3000,
    int? timeWindowHours,
  }) {
    return getAllHotspots(
      timeWindowHours: timeWindowHours,
      lat: lat,
      lon: lon,
      radiusMeters: radiusMeters,
    );
  }

  void dispose() {
    _client.close();
  }
}

