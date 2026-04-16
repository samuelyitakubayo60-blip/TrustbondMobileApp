enum OfflineReportSyncState { pending, syncing, failed }

class OfflineReportMediaItem {
  final String localPath;
  final String fileType;
  final bool isLiveCapture;
  final String capturedAt;

  const OfflineReportMediaItem({
    required this.localPath,
    required this.fileType,
    required this.isLiveCapture,
    required this.capturedAt,
  });

  factory OfflineReportMediaItem.fromJson(Map<String, dynamic> json) {
    return OfflineReportMediaItem(
      localPath: json['local_path'] as String? ?? '',
      fileType: json['file_type'] as String? ?? 'photo',
      isLiveCapture: json['is_live_capture'] as bool? ?? false,
      capturedAt: json['captured_at'] as String? ?? DateTime.now().toIso8601String(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'local_path': localPath,
      'file_type': fileType,
      'is_live_capture': isLiveCapture,
      'captured_at': capturedAt,
    };
  }
}

class OfflineReportQueueItem {
  static const Object _unset = Object();

  final String localReportId;
  final String? deviceId;
  final String deviceHash;
  final int incidentTypeId;
  final String incidentTypeName;
  final String description;
  final double latitude;
  final double longitude;
  final double? gpsAccuracy;
  final String submittedAt;
  final String networkTypeAtSubmit;
  final double? batteryLevel;
  final String? motionLevel;
  final double? movementSpeed;
  final bool? wasStationary;
  final List<String> contextTags;
  final List<OfflineReportMediaItem> mediaItems;
  final OfflineReportSyncState state;
  final int retryCount;
  final String? nextRetryAt;
  final String? lastError;

  const OfflineReportQueueItem({
    required this.localReportId,
    required this.deviceId,
    required this.deviceHash,
    required this.incidentTypeId,
    required this.incidentTypeName,
    required this.description,
    required this.latitude,
    required this.longitude,
    required this.gpsAccuracy,
    required this.submittedAt,
    required this.networkTypeAtSubmit,
    required this.batteryLevel,
    required this.motionLevel,
    required this.movementSpeed,
    required this.wasStationary,
    required this.contextTags,
    required this.mediaItems,
    required this.state,
    required this.retryCount,
    required this.nextRetryAt,
    required this.lastError,
  });

  factory OfflineReportQueueItem.fromJson(Map<String, dynamic> json) {
    return OfflineReportQueueItem(
      localReportId: json['local_report_id'] as String? ?? '',
      deviceId: json['device_id'] as String?,
      deviceHash: json['device_hash'] as String? ?? '',
      incidentTypeId: json['incident_type_id'] as int? ?? 0,
      incidentTypeName: json['incident_type_name'] as String? ?? 'Incident',
      description: json['description'] as String? ?? '',
      latitude: (json['latitude'] as num?)?.toDouble() ?? 0,
      longitude: (json['longitude'] as num?)?.toDouble() ?? 0,
      gpsAccuracy: (json['gps_accuracy'] as num?)?.toDouble(),
      submittedAt: json['submitted_at'] as String? ?? DateTime.now().toIso8601String(),
      networkTypeAtSubmit: json['network_type_at_submit'] as String? ?? 'Offline',
      batteryLevel: (json['battery_level'] as num?)?.toDouble(),
      motionLevel: json['motion_level'] as String?,
      movementSpeed: (json['movement_speed'] as num?)?.toDouble(),
      wasStationary: json['was_stationary'] as bool?,
      contextTags: (json['context_tags'] as List<dynamic>? ?? const [])
          .map((tag) => tag.toString())
          .toList(growable: false),
      mediaItems: (json['media_items'] as List<dynamic>? ?? const [])
          .whereType<Map>()
          .map((item) => OfflineReportMediaItem.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(growable: false),
      state: _stateFromJson(json['state'] as String?),
      retryCount: json['retry_count'] as int? ?? 0,
      nextRetryAt: json['next_retry_at'] as String?,
      lastError: json['last_error'] as String?,
    );
  }

  static OfflineReportSyncState _stateFromJson(String? value) {
    return switch (value) {
      'syncing' => OfflineReportSyncState.syncing,
      'failed' => OfflineReportSyncState.failed,
      _ => OfflineReportSyncState.pending,
    };
  }

  DateTime get submittedAtDate => DateTime.parse(submittedAt).toLocal();

  DateTime? get nextRetryAtDate =>
      nextRetryAt == null ? null : DateTime.tryParse(nextRetryAt!)?.toLocal();

  Map<String, dynamic> toJson() {
    return {
      'local_report_id': localReportId,
      'device_id': deviceId,
      'device_hash': deviceHash,
      'incident_type_id': incidentTypeId,
      'incident_type_name': incidentTypeName,
      'description': description,
      'latitude': latitude,
      'longitude': longitude,
      'gps_accuracy': gpsAccuracy,
      'submitted_at': submittedAt,
      'network_type_at_submit': networkTypeAtSubmit,
      'battery_level': batteryLevel,
      'motion_level': motionLevel,
      'movement_speed': movementSpeed,
      'was_stationary': wasStationary,
      'context_tags': contextTags,
      'media_items': mediaItems.map((item) => item.toJson()).toList(growable: false),
      'state': state.name,
      'retry_count': retryCount,
      'next_retry_at': nextRetryAt,
      'last_error': lastError,
    };
  }

  OfflineReportQueueItem copyWith({
    Object? deviceId = _unset,
    OfflineReportSyncState? state,
    int? retryCount,
    Object? nextRetryAt = _unset,
    Object? lastError = _unset,
  }) {
    return OfflineReportQueueItem(
      localReportId: localReportId,
      deviceId: identical(deviceId, _unset) ? this.deviceId : deviceId as String?,
      deviceHash: deviceHash,
      incidentTypeId: incidentTypeId,
      incidentTypeName: incidentTypeName,
      description: description,
      latitude: latitude,
      longitude: longitude,
      gpsAccuracy: gpsAccuracy,
      submittedAt: submittedAt,
      networkTypeAtSubmit: networkTypeAtSubmit,
      batteryLevel: batteryLevel,
      motionLevel: motionLevel,
      movementSpeed: movementSpeed,
      wasStationary: wasStationary,
      contextTags: contextTags,
      mediaItems: mediaItems,
      state: state ?? this.state,
      retryCount: retryCount ?? this.retryCount,
      nextRetryAt: identical(nextRetryAt, _unset)
          ? this.nextRetryAt
          : nextRetryAt as String?,
      lastError: identical(lastError, _unset)
          ? this.lastError
          : lastError as String?,
    );
  }
}
