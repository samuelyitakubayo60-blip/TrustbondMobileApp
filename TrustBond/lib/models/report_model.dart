import 'package:flutter/foundation.dart';
import '../utils/date_time_utils.dart';

/// One report as returned from GET /reports (list or detail).

class ReportListItem {

  final String reportId;

  final String deviceId;

  final int incidentTypeId;

  final String? incidentTypeName;

  final String? description;

  final double latitude;

  final double longitude;

  final DateTime reportedAt;

  final String ruleStatus;

  final String? status;

  final String? verificationStatus;

  final double? trustScore;

  final String? reportNumber;

  final List<String> contextTags;

  final bool? isFlagged;

  final String? flagReason;

  final DateTime? verifiedAt;



  ReportListItem({

    required this.reportId,

    required this.deviceId,

    required this.incidentTypeId,

    this.incidentTypeName,

    this.description,

    required this.latitude,

    required this.longitude,

    required this.reportedAt,

    required this.ruleStatus,

    this.status,

    this.verificationStatus,

    this.trustScore,

    this.reportNumber,

    this.contextTags = const [],

    this.isFlagged,

    this.flagReason,

    this.verifiedAt,

  });



  factory ReportListItem.fromJson(Map<String, dynamic> json) {
    try {
      final tags = json['context_tags'];

      return ReportListItem(
        reportId: _stringFromJson(json['report_id']),
        deviceId: _stringFromJson(json['device_id']),
        incidentTypeId: _intFromJson(json['incident_type_id']),
        incidentTypeName: json['incident_type_name'] as String?,
        description: json['description'] as String?,
        latitude: _doubleFromJson(json['latitude']),
        longitude: _doubleFromJson(json['longitude']),
        reportedAt: parseApiDateTimeToLocal(_stringFromJson(json['reported_at'])),
        ruleStatus: json['rule_status'] as String? ?? 'pending',
        status: json['status'] as String?,
        verificationStatus: json['verification_status'] as String?,
        trustScore: _doubleFromJson(json['trust_score']),
        reportNumber: json['report_number'] as String?,
        contextTags: tags is List ? tags.map((e) => e.toString()).toList() : [],
        isFlagged: json['is_flagged'] as bool?,
        flagReason: json['flag_reason'] as String?,
        verifiedAt: json['verified_at'] != null ? parseApiDateTimeToLocal(json['verified_at'] as String) : null,
      );
    } catch (e) {
      debugPrint('Error parsing ReportListItem: $e');
      debugPrint('JSON data: $json');
      
      // Try to identify the specific field causing issues
      final fields = ['report_id', 'device_id', 'incident_type_id', 'latitude', 'longitude', 'reported_at', 'trust_score'];
      for (final field in fields) {
        final value = json[field];
        debugPrint('Field $field: $value (type: ${value.runtimeType})');
      }
      
      rethrow;
    }
  }

  String get workflowStatus =>
      (verificationStatus ?? status ?? ruleStatus).trim().toLowerCase();

}



/// One evidence file as returned in report detail.

class ReportEvidenceItem {

  final String evidenceId;

  final String fileUrl;

  final String fileType; // photo | video

  final String? aiQualityLabel; // good, fair, poor, suspicious (from ML/DB)

  final double? blurScore;

  final double? tamperScore;



  ReportEvidenceItem({

    required this.evidenceId,

    required this.fileUrl,

    required this.fileType,

    this.aiQualityLabel,

    this.blurScore,

    this.tamperScore,

  });



  factory ReportEvidenceItem.fromJson(Map<String, dynamic> json) {

    return ReportEvidenceItem(

      evidenceId: _stringFromJson(json['evidence_id']),

      fileUrl: _stringFromJson(json['file_url']),

      fileType: json['file_type'] as String? ?? 'photo',

      // Backend may send either ai_quality_label (old) or quality_label (new).

      aiQualityLabel: (json['ai_quality_label'] ?? json['quality_label']) as String?,

      blurScore: _doubleFromJson(json['blur_score']),

      tamperScore: _doubleFromJson(json['tamper_score']),

    );

  }

}



/// Report detail with evidence (from GET /reports/:id).

class ReportDetailItem {

  final String reportId;

  final String deviceId;

  final int incidentTypeId;

  final String? incidentTypeName;

  final String? description;

  final double latitude;

  final double longitude;

  final DateTime reportedAt;

  final String ruleStatus;

  final String? status;

  final String? verificationStatus;

  final List<ReportEvidenceItem> evidenceFiles;

  final double? trustScore;

  final String? reportNumber;

  final List<String> contextTags;

  final bool? isFlagged;

  final String? flagReason;

  final DateTime? verifiedAt;

  final Map<String, int> communityVotes;

  final String? userVote;



  ReportDetailItem({

    required this.reportId,

    required this.deviceId,

    required this.incidentTypeId,

    this.incidentTypeName,

    this.description,

    required this.latitude,

    required this.longitude,

    required this.reportedAt,

    required this.ruleStatus,

    this.status,

    this.verificationStatus,

    this.evidenceFiles = const [],

    this.trustScore,

    this.reportNumber,

    this.contextTags = const [],

    this.isFlagged,

    this.flagReason,

    this.verifiedAt,

    this.communityVotes = const {},

    this.userVote,

  });



  factory ReportDetailItem.fromJson(Map<String, dynamic> json) {

    final evidenceList = json['evidence_files'] as List<dynamic>? ?? [];

    final tags = json['context_tags'];

    final Map<String, int> votes = {};
    if (json['community_votes'] is Map) {
      (json['community_votes'] as Map).forEach((k, v) {
        votes[k.toString()] = _intFromJson(v);
      });
    }

    return ReportDetailItem(

      reportId: _stringFromJson(json['report_id']),

      deviceId: _stringFromJson(json['device_id']),

      incidentTypeId: _intFromJson(json['incident_type_id']),

      incidentTypeName: json['incident_type_name'] as String?,

      description: json['description'] as String?,

      latitude: _doubleFromJson(json['latitude']),

      longitude: _doubleFromJson(json['longitude']),

      reportedAt: parseApiDateTimeToLocal(_stringFromJson(json['reported_at'])),

      ruleStatus: json['rule_status'] as String? ?? 'pending',

      status: json['status'] as String?,

      verificationStatus: json['verification_status'] as String?,

      evidenceFiles: evidenceList

          .map((e) => ReportEvidenceItem.fromJson(e as Map<String, dynamic>))

          .toList(),

      trustScore: _doubleFromJson(json['trust_score']),

      reportNumber: json['report_number'] as String?,

      contextTags: tags is List ? tags.map((e) => e.toString()).toList() : [],

      isFlagged: json['is_flagged'] as bool?,

      flagReason: json['flag_reason'] as String?,

      verifiedAt: json['verified_at'] != null ? parseApiDateTimeToLocal(json['verified_at'] as String) : null,

      communityVotes: votes,

      userVote: json['user_vote'] as String?,

    );

  }

  String get workflowStatus =>
      (verificationStatus ?? status ?? ruleStatus).trim().toLowerCase();

}



double _doubleFromJson(dynamic value) {
  if (value == null) return 0.0;
  
  if (value is double) return value;
  if (value is int) return value.toDouble();
  if (value is num) return value.toDouble();
  
  if (value is String) {
    // Handle string conversion more robustly
    final cleanValue = value.trim();
    if (cleanValue.isEmpty) return 0.0;
    
    // Try parsing as double
    final parsed = double.tryParse(cleanValue);
    if (parsed != null) return parsed;
    
    // Try removing quotes if present
    if (cleanValue.startsWith('"') && cleanValue.endsWith('"')) {
      final innerValue = cleanValue.substring(1, cleanValue.length - 1);
      final innerParsed = double.tryParse(innerValue);
      if (innerParsed != null) return innerParsed;
    }
  }
  
  return 0.0;
}

int _intFromJson(dynamic value) {
  if (value == null) return 0;
  
  if (value is int) return value;
  if (value is double) return value.toInt();
  if (value is num) return value.toInt();
  
  if (value is String) {
    // Handle string conversion more robustly
    final cleanValue = value.trim();
    if (cleanValue.isEmpty) return 0;
    
    // Try parsing as int
    final parsed = int.tryParse(cleanValue);
    if (parsed != null) return parsed;
    
    // Try parsing as double first, then convert to int
    final doubleParsed = double.tryParse(cleanValue);
    if (doubleParsed != null) return doubleParsed.toInt();
    
    // Try removing quotes if present
    if (cleanValue.startsWith('"') && cleanValue.endsWith('"')) {
      final innerValue = cleanValue.substring(1, cleanValue.length - 1);
      final innerParsed = int.tryParse(innerValue);
      if (innerParsed != null) return innerParsed;
    }
  }
  
  return 0;
}

String _stringFromJson(dynamic value) {
  if (value == null) return '';
  
  if (value is String) return value;
  
  // Convert other types to string
  return value.toString();
}



class ReportModel {

  final String deviceId;

  final int incidentTypeId;

  final String? description;

  final double latitude;

  final double longitude;

  final double? gpsAccuracy;

  final String? motionLevel;

  final double? movementSpeed;

  final bool? wasStationary;

  final List<EvidenceFileModel> evidenceFiles;



  ReportModel({

    required this.deviceId,

    required this.incidentTypeId,

    this.description,

    required this.latitude,

    required this.longitude,

    this.gpsAccuracy,

    this.motionLevel,

    this.movementSpeed,

    this.wasStationary,

    this.evidenceFiles = const [],

  });



  Map<String, dynamic> toJson() {

    return {

      'device_id': deviceId,

      'incident_type_id': incidentTypeId,

      'description': description,

      'latitude': latitude,

      'longitude': longitude,

      'gps_accuracy': gpsAccuracy,

      'motion_level': motionLevel,

      'movement_speed': movementSpeed,

      'was_stationary': wasStationary,

      'evidence_files': evidenceFiles.map((e) => e.toJson()).toList(),

    };

  }

}



class EvidenceFileModel {

  final String fileUrl;

  final String fileType;

  final double? mediaLatitude;

  final double? mediaLongitude;

  final DateTime? capturedAt;

  final bool isLiveCapture;



  EvidenceFileModel({

    required this.fileUrl,

    required this.fileType,

    this.mediaLatitude,

    this.mediaLongitude,

    this.capturedAt,

    this.isLiveCapture = false,

  });



  Map<String, dynamic> toJson() {

    return {

      'file_url': fileUrl,

      'file_type': fileType,

      'media_latitude': mediaLatitude,

      'media_longitude': mediaLongitude,

      'captured_at': capturedAt?.toIso8601String(),

      'is_live_capture': isLiveCapture,

    };

  }

}

