import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';

class MLPrediction {
  final String predictionId;
  final String reportId;
  final double trustScore;
  final String predictionLabel; // likely_real, suspicious, fake
  final String modelVersion;
  final double confidence;
  final DateTime evaluatedAt;
  final Map<String, dynamic>? explanation;
  final String? modelType;
  final bool isFinal;

  MLPrediction({
    required this.predictionId,
    required this.reportId,
    required this.trustScore,
    required this.predictionLabel,
    required this.modelVersion,
    required this.confidence,
    required this.evaluatedAt,
    this.explanation,
    this.modelType,
    required this.isFinal,
  });

  factory MLPrediction.fromJson(Map<String, dynamic> json) {
    return MLPrediction(
      predictionId: json['prediction_id'] ?? '',
      reportId: json['report_id'] ?? '',
      trustScore: (json['trust_score'] ?? 0.0).toDouble(),
      predictionLabel: json['prediction_label'] ?? 'unknown',
      modelVersion: json['model_version'] ?? 'unknown',
      confidence: (json['confidence'] ?? 0.0).toDouble(),
      evaluatedAt: DateTime.tryParse(json['evaluated_at'] ?? '') ?? DateTime.now(),
      explanation: json['explanation'],
      modelType: json['model_type'],
      isFinal: json['is_final'] ?? false,
    );
  }

  String get statusText {
    switch (predictionLabel) {
      case 'likely_real':
        return 'Highly Credible';
      case 'suspicious':
        return 'Needs Review';
      case 'fake':
        return 'Low Credibility';
      default:
        return 'Unknown';
    }
  }

  String get statusEmoji {
    switch (predictionLabel) {
      case 'likely_real':
        return '✅';
      case 'suspicious':
        return '⚠️';
      case 'fake':
        return '❌';
      default:
        return '❓';
    }
  }
}

class MLInsight {
  final String title;
  final String description;
  final String type; // safety, trust, pattern
  final double? score;
  final DateTime timestamp;

  MLInsight({
    required this.title,
    required this.description,
    required this.type,
    this.score,
    required this.timestamp,
  });
}

class MLService {
  static final MLService _instance = MLService._internal();
  factory MLService() => _instance;
  MLService._internal();

  final http.Client _client = http.Client();
  static const Duration _timeout = Duration(seconds: 30);

  /// Fetch ML prediction for a specific report
  Future<MLPrediction?> getReportPrediction(String reportId, String deviceId) async {
    try {
      final uri = Uri.parse('${ApiConfig.devicesUrl}/reports/$reportId/prediction').replace(
        queryParameters: {'device_id': deviceId},
      );
      
      final response = await _client.get(uri).timeout(_timeout);
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        return MLPrediction.fromJson(data);
      } else if (response.statusCode == 404) {
        // No prediction available yet
        return null;
      }
      
      throw Exception('Failed to fetch prediction: ${response.statusCode}');
    } catch (e) {
      // Silently fail for non-critical ML features
      return null;
    }
  }

  /// Fetch ML insights for the home dashboard
  Future<List<MLInsight>> getHomeInsights(String deviceId) async {
    try {
      final uri = Uri.parse('${ApiConfig.devicesUrl}/ml-insights').replace(
        queryParameters: {'device_id': deviceId},
      );
      
      final response = await _client.get(uri).timeout(_timeout);
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as List<dynamic>;
        return data.map((item) => MLInsight(
          title: item['title'] ?? 'Insight',
          description: item['description'] ?? '',
          type: item['type'] ?? 'general',
          score: (item['score'] as num?)?.toDouble(),
          timestamp: DateTime.tryParse(item['timestamp'] ?? '') ?? DateTime.now(),
        )).toList();
      }
      
      return [];
    } catch (e) {
      // Return empty list on error
      return [];
    }
  }

  /// Get device ML statistics
  Future<Map<String, dynamic>> getDeviceMLStats(String deviceId) async {
    try {
      final uri = Uri.parse('${ApiConfig.devicesUrl}/$deviceId/ml-stats');
      
      final response = await _client.get(uri).timeout(_timeout);
      
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      
      return {};
    } catch (e) {
      return {};
    }
  }

  /// Batch fetch predictions for multiple reports
  Future<Map<String, MLPrediction>> getBatchPredictions(
    List<String> reportIds, 
    String deviceId
  ) async {
    final Map<String, MLPrediction> predictions = {};
    
    for (final reportId in reportIds) {
      try {
        final prediction = await getReportPrediction(reportId, deviceId);
        if (prediction != null) {
          predictions[reportId] = prediction;
        }
      } catch (e) {
        // Continue with other reports
        continue;
      }
    }
    
    return predictions;
  }
}
