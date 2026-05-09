import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';

class GuidanceRequest {
  final String description;
  final String incidentType;
  final int evidenceCount;
  final List<String> fileTypes;
  final double? gpsAccuracy;
  final double? movementSpeed;
  final String? deviceId;
  final bool hasLiveCapture;
  final bool isOffline;

  GuidanceRequest({
    required this.description,
    required this.incidentType,
    this.evidenceCount = 0,
    this.fileTypes = const [],
    this.gpsAccuracy,
    this.movementSpeed,
    this.deviceId,
    this.hasLiveCapture = false,
    this.isOffline = true,
  });

  Map<String, dynamic> toJson() {
    return {
      'description': description,
      'incident_type': incidentType,
      'evidence_count': evidenceCount,
      'file_types': fileTypes,
      'gps_accuracy': gpsAccuracy,
      'movement_speed': movementSpeed,
      'device_id': deviceId,
      'has_live_capture': hasLiveCapture,
      'is_offline': isOffline,
    };
  }
}

class GuidanceItem {
  final String level;
  final String title;
  final String message;
  final bool actionable;
  final String? suggestedAction;

  GuidanceItem({
    required this.level,
    required this.title,
    required this.message,
    this.actionable = true,
    this.suggestedAction,
  });

  factory GuidanceItem.fromJson(Map<String, dynamic> json) {
    return GuidanceItem(
      level: json['level'],
      title: json['title'],
      message: json['message'],
      actionable: json['actionable'] ?? true,
      suggestedAction: json['suggested_action'],
    );
  }
}

class TrustScoreEstimate {
  final double totalScore;
  final double trustbondScore;
  final double naturalLanguageScore;
  final double? voloScore;
  final double baseScore;
  final String confidence;
  final bool willBeVerified;
  final int contributingModels;

  TrustScoreEstimate({
    required this.totalScore,
    required this.trustbondScore,
    required this.naturalLanguageScore,
    this.voloScore,
    required this.baseScore,
    required this.confidence,
    required this.willBeVerified,
    required this.contributingModels,
  });

  factory TrustScoreEstimate.fromJson(Map<String, dynamic> json) {
    return TrustScoreEstimate(
      totalScore: (json['total_score'] as num).toDouble(),
      trustbondScore: (json['trustbond_score'] as num).toDouble(),
      naturalLanguageScore: (json['natural_language_score'] as num).toDouble(),
      voloScore: json['volo_score'] != null ? (json['volo_score'] as num).toDouble() : null,
      baseScore: (json['base_score'] as num).toDouble(),
      confidence: json['confidence'],
      willBeVerified: json['will_be_verified'],
      contributingModels: json['contributing_models'],
    );
  }

  String get confidenceLevel {
    switch (confidence) {
      case 'high_confidence':
        return 'High';
      case 'medium_confidence':
        return 'Medium';
      case 'low_confidence':
        return 'Low';
      case 'reject':
        return 'Very Low';
      default:
        return 'Unknown';
    }
  }

  String get verificationProbability {
    if (willBeVerified) return 'Very High';
    switch (confidence) {
      case 'high_confidence':
        return 'High';
      case 'medium_confidence':
        return 'Medium';
      case 'low_confidence':
        return 'Low';
      case 'reject':
        return 'Very Low';
      default:
        return 'Unknown';
    }
  }
}

class GuidanceResponse {
  final List<GuidanceItem> guidanceItems;
  final TrustScoreEstimate trustEstimate;
  final String summary;
  final List<String> priorityActions;

  GuidanceResponse({
    required this.guidanceItems,
    required this.trustEstimate,
    required this.summary,
    required this.priorityActions,
  });

  factory GuidanceResponse.fromJson(Map<String, dynamic> json) {
    return GuidanceResponse(
      guidanceItems: (json['guidance_items'] as List)
          .map((item) => GuidanceItem.fromJson(item))
          .toList(),
      trustEstimate: TrustScoreEstimate.fromJson(json['trust_estimate']),
      summary: json['summary'],
      priorityActions: List<String>.from(json['priority_actions']),
    );
  }

  List<GuidanceItem> get criticalItems =>
      guidanceItems.where((item) => item.level == 'critical').toList();

  List<GuidanceItem> get warningItems =>
      guidanceItems.where((item) => item.level == 'warning').toList();

  List<GuidanceItem> get infoItems =>
      guidanceItems.where((item) => item.level == 'info').toList();

  List<GuidanceItem> get successItems =>
      guidanceItems.where((item) => item.level == 'success').toList();
}

class DescriptionValidationResponse {
  final bool isValid;
  final int wordCount;
  final double qualityScore;
  final List<String> suggestions;
  final List<String> missingKeywords;

  DescriptionValidationResponse({
    required this.isValid,
    required this.wordCount,
    required this.qualityScore,
    required this.suggestions,
    required this.missingKeywords,
  });

  factory DescriptionValidationResponse.fromJson(Map<String, dynamic> json) {
    return DescriptionValidationResponse(
      isValid: json['is_valid'],
      wordCount: json['word_count'],
      qualityScore: (json['quality_score'] as num).toDouble(),
      suggestions: List<String>.from(json['suggestions']),
      missingKeywords: List<String>.from(json['missing_keywords']),
    );
  }
}

class EvidenceValidationResponse {
  final bool isSufficient;
  final double qualityScore;
  final List<String> suggestions;
  final int idealCount;

  EvidenceValidationResponse({
    required this.isSufficient,
    required this.qualityScore,
    required this.suggestions,
    required this.idealCount,
  });

  factory EvidenceValidationResponse.fromJson(Map<String, dynamic> json) {
    return EvidenceValidationResponse(
      isSufficient: json['is_sufficient'],
      qualityScore: (json['quality_score'] as num).toDouble(),
      suggestions: List<String>.from(json['suggestions']),
      idealCount: json['ideal_count'],
    );
  }
}

class IncidentKeywordsResponse {
  final List<String> keywords;
  final String incidentType;

  IncidentKeywordsResponse({
    required this.keywords,
    required this.incidentType,
  });

  factory IncidentKeywordsResponse.fromJson(Map<String, dynamic> json) {
    return IncidentKeywordsResponse(
      keywords: List<String>.from(json['keywords']),
      incidentType: json['incident_type'],
    );
  }
}

class GuidanceThresholdsResponse {
  final Map<String, dynamic> description;
  final Map<String, dynamic> evidence;
  final Map<String, dynamic> location;
  final Map<String, dynamic> modelWeights;

  GuidanceThresholdsResponse({
    required this.description,
    required this.evidence,
    required this.location,
    required this.modelWeights,
  });

  factory GuidanceThresholdsResponse.fromJson(Map<String, dynamic> json) {
    return GuidanceThresholdsResponse(
      description: Map<String, dynamic>.from(json['description']),
      evidence: Map<String, dynamic>.from(json['evidence']),
      location: Map<String, dynamic>.from(json['location']),
      modelWeights: Map<String, dynamic>.from(json['model_weights']),
    );
  }
}

class GuidanceService {
  static const Duration _timeout = Duration(seconds: 10);
  static const int _maxRetries = 2;

  static Future<GuidanceResponse> analyzeSubmission(GuidanceRequest request) async {
    final url = '${ApiConfig.baseUrl}/submission-guidance/analyze';
    
    for (int attempt = 0; attempt <= _maxRetries; attempt++) {
      try {
        final response = await http.post(
          Uri.parse(url),
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: json.encode(request.toJson()),
        ).timeout(_timeout);

        if (response.statusCode == 200) {
          final data = json.decode(response.body);
          return GuidanceResponse.fromJson(data);
        } else {
          throw Exception('Failed to analyze submission: ${response.statusCode}');
        }
      } catch (e) {
        if (attempt == _maxRetries) {
          // Return fallback response for offline mode
          return _createFallbackGuidance(request);
        }
        // Wait before retry
        await Future.delayed(Duration(milliseconds: 500 * (attempt + 1)));
      }
    }
    
    throw Exception('Failed to analyze submission after $_maxRetries attempts');
  }

  static Future<DescriptionValidationResponse> validateDescription(
    String description,
    String incidentType,
  ) async {
    final url = '${ApiConfig.baseUrl}/submission-guidance/validate-description';
    
    try {
      final response = await http.post(
        Uri.parse(url),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: json.encode({
          'description': description,
          'incident_type': incidentType,
        }),
      ).timeout(_timeout);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return DescriptionValidationResponse.fromJson(data);
      } else {
        throw Exception('Failed to validate description: ${response.statusCode}');
      }
    } catch (e) {
      // Return fallback for offline mode
      return _createFallbackDescriptionValidation(description, incidentType);
    }
  }

  static Future<EvidenceValidationResponse> validateEvidence(
    int evidenceCount,
    bool hasLiveCapture, {
    List<String>? fileTypes,
  }) async {
    final url = '${ApiConfig.baseUrl}/submission-guidance/validate-evidence';
    
    try {
      final response = await http.post(
        Uri.parse(url),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: json.encode({
          'evidence_count': evidenceCount,
          'has_live_capture': hasLiveCapture,
          'file_types': fileTypes ?? [],
        }),
      ).timeout(_timeout);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return EvidenceValidationResponse.fromJson(data);
      } else {
        throw Exception('Failed to validate evidence: ${response.statusCode}');
      }
    } catch (e) {
      // Return fallback for offline mode
      return _createFallbackEvidenceValidation(evidenceCount, hasLiveCapture);
    }
  }

  static Future<IncidentKeywordsResponse> getIncidentKeywords(String incidentType) async {
    final url = '${ApiConfig.baseUrl}/submission-guidance/incident-keywords/$incidentType';
    
    try {
      final response = await http.get(
        Uri.parse(url),
        headers: {
          'Accept': 'application/json',
        },
      ).timeout(_timeout);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return IncidentKeywordsResponse.fromJson(data);
      } else {
        throw Exception('Failed to get incident keywords: ${response.statusCode}');
      }
    } catch (e) {
      // Return fallback for offline mode
      return _createFallbackKeywords(incidentType);
    }
  }

  static Future<GuidanceThresholdsResponse> getGuidanceThresholds() async {
    final url = '${ApiConfig.baseUrl}/submission-guidance/thresholds';
    
    try {
      final response = await http.get(
        Uri.parse(url),
        headers: {
          'Accept': 'application/json',
        },
      ).timeout(_timeout);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return GuidanceThresholdsResponse.fromJson(data);
      } else {
        throw Exception('Failed to get guidance thresholds: ${response.statusCode}');
      }
    } catch (e) {
      // Return fallback for offline mode
      return _createFallbackThresholds();
    }
  }

  // Fallback methods for offline mode
  static GuidanceResponse _createFallbackGuidance(GuidanceRequest request) {
    final wordCount = request.description.split(' ').length;
    final items = <GuidanceItem>[];

    // Basic description validation
    if (wordCount < 15) {
      items.add(GuidanceItem(
        level: 'critical',
        title: 'Description Too Brief',
        message: 'Add more details for better verification.',
        suggestedAction: 'Include details about location, time, and people involved.',
      ));
    }

    // Basic evidence validation
    if (request.evidenceCount == 0) {
      items.add(GuidanceItem(
        level: 'critical',
        title: 'No Evidence Added',
        message: 'Reports with evidence are more likely to be verified.',
        suggestedAction: 'Add photos or videos of the incident.',
      ));
    }

    // Basic location validation
    if (request.gpsAccuracy == null) {
      items.add(GuidanceItem(
        level: 'critical',
        title: 'No Location Data',
        message: 'GPS location is required for verification.',
        suggestedAction: 'Enable location services.',
      ));
    }

    final trustScore = TrustScoreEstimate(
      totalScore: 50.0,
      trustbondScore: 50.0,
      naturalLanguageScore: 50.0,
      voloScore: 0.0,
      baseScore: 10.0,
      confidence: 'medium_confidence',
      willBeVerified: false,
      contributingModels: 2,
    );

    return GuidanceResponse(
      guidanceItems: items,
      trustEstimate: trustScore,
      summary: 'Basic analysis completed. Add more details for better verification.',
      priorityActions: items.map((item) => item.suggestedAction ?? '').toList(),
    );
  }

  static DescriptionValidationResponse _createFallbackDescriptionValidation(
    String description,
    String incidentType,
  ) {
    final wordCount = description.split(' ').length;
    final qualityScore = (wordCount * 2.0).clamp(0.0, 100.0);
    final isValid = wordCount >= 15;

    return DescriptionValidationResponse(
      isValid: isValid,
      wordCount: wordCount,
      qualityScore: qualityScore,
      suggestions: isValid ? [] : ['Add more details about the incident'],
      missingKeywords: [],
    );
  }

  static EvidenceValidationResponse _createFallbackEvidenceValidation(
    int evidenceCount,
    bool hasLiveCapture,
  ) {
    final qualityScore = (evidenceCount * 25.0 + (hasLiveCapture ? 10.0 : 0.0)).clamp(0.0, 100.0);
    final isSufficient = evidenceCount >= 1;

    return EvidenceValidationResponse(
      isSufficient: isSufficient,
      qualityScore: qualityScore,
      suggestions: isSufficient ? [] : ['Add photos or videos as evidence'],
      idealCount: 3,
    );
  }

  static IncidentKeywordsResponse _createFallbackKeywords(String incidentType) {
    final keywords = _getBasicKeywords(incidentType);
    return IncidentKeywordsResponse(
      keywords: keywords,
      incidentType: incidentType,
    );
  }

  static GuidanceThresholdsResponse _createFallbackThresholds() {
    return GuidanceThresholdsResponse(
      description: {'min_length': 15, 'ideal_length': 50},
      evidence: {'min_count': 1, 'ideal_count': 3},
      location: {'min_gps_accuracy': 50},
      modelWeights: {'trustbond': 0.4, 'natural_language': 0.3, 'volo': 0.2, 'base': 0.1},
    );
  }

  static List<String> _getBasicKeywords(String incidentType) {
    switch (incidentType.toLowerCase()) {
      case 'assault':
        return ['person', 'location', 'time', 'weapon', 'injured'];
      case 'theft':
        return ['stolen', 'property', 'location', 'time', 'thief'];
      case 'vandalism':
        return ['damaged', 'property', 'location', 'time', 'broken'];
      case 'drugs':
        return ['drugs', 'location', 'time', 'using', 'selling'];
      case 'fire':
        return ['fire', 'location', 'time', 'burning', 'smoke'];
      case 'accident':
        return ['accident', 'location', 'time', 'injured', 'vehicle'];
      default:
        return ['person', 'location', 'time', 'description'];
    }
  }
}
