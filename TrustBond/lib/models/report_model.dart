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
  final double? trustScore;
  final String? reportNumber;
  final List<String> contextTags;
  final bool? isFlagged;
  final String? flagReason;

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
    this.trustScore,
    this.reportNumber,
    this.contextTags = const [],
    this.isFlagged,
    this.flagReason,
  });

  factory ReportListItem.fromJson(Map<String, dynamic> json) {
    final tags = json['context_tags'];
    return ReportListItem(
      reportId: _stringFromJson(json['report_id']),
      deviceId: _stringFromJson(json['device_id']),
      incidentTypeId: _intFromJson(json['incident_type_id']),
      incidentTypeName: json['incident_type_name'] as String?,
      description: json['description'] as String?,
      latitude: _doubleFromJson(json['latitude']),
      longitude: _doubleFromJson(json['longitude']),
      reportedAt: DateTime.parse(_stringFromJson(json['reported_at'])),
      ruleStatus: json['rule_status'] as String? ?? 'pending',
      trustScore: (json['trust_score'] as num?)?.toDouble(),
      reportNumber: json['report_number'] as String?,
      contextTags: tags is List ? (tags as List).map((e) => e.toString()).toList() : [],
      isFlagged: json['is_flagged'] as bool?,
      flagReason: json['flag_reason'] as String?,
    );
  }
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
      aiQualityLabel: json['ai_quality_label'] as String?,
      blurScore: (json['blur_score'] as num?)?.toDouble(),
      tamperScore: (json['tamper_score'] as num?)?.toDouble(),
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
  final List<ReportEvidenceItem> evidenceFiles;
  final double? trustScore;
  final String? reportNumber;
  final List<String> contextTags;
  final bool? isFlagged;
  final String? flagReason;

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
    this.evidenceFiles = const [],
    this.trustScore,
    this.reportNumber,
    this.contextTags = const [],
    this.isFlagged,
    this.flagReason,
  });

  factory ReportDetailItem.fromJson(Map<String, dynamic> json) {
    final evidenceList = json['evidence_files'] as List<dynamic>? ?? [];
    final tags = json['context_tags'];
    return ReportDetailItem(
      reportId: _stringFromJson(json['report_id']),
      deviceId: _stringFromJson(json['device_id']),
      incidentTypeId: _intFromJson(json['incident_type_id']),
      incidentTypeName: json['incident_type_name'] as String?,
      description: json['description'] as String?,
      latitude: _doubleFromJson(json['latitude']),
      longitude: _doubleFromJson(json['longitude']),
      reportedAt: DateTime.parse(_stringFromJson(json['reported_at'])),
      ruleStatus: json['rule_status'] as String? ?? 'pending',
      evidenceFiles: evidenceList
          .map((e) => ReportEvidenceItem.fromJson(e as Map<String, dynamic>))
          .toList(),
      trustScore: (json['trust_score'] as num?)?.toDouble(),
      reportNumber: json['report_number'] as String?,
      contextTags: tags is List ? (tags as List).map((e) => e.toString()).toList() : [],
      isFlagged: json['is_flagged'] as bool?,
      flagReason: json['flag_reason'] as String?,
    );
  }
}

double _doubleFromJson(dynamic value) {
  if (value == null) return 0.0;
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value) ?? 0.0;
  return 0.0;
}

int _intFromJson(dynamic value) {
  if (value == null) return 0;
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value) ?? 0;
  return 0;
}

String _stringFromJson(dynamic value) {
  if (value == null) return '';
  if (value is String) return value;
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
