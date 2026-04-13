import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/offline_report_queue_item.dart';
import 'api_service.dart';
import 'app_refresh_bus.dart';
import 'device_service.dart';
import 'device_status_service.dart';

class OfflineSubmitResult {
  final String reportId;
  final bool queuedOffline;

  const OfflineSubmitResult({
    required this.reportId,
    required this.queuedOffline,
  });
}

class OfflineReportQueueService {
  OfflineReportQueueService._internal();

  static final OfflineReportQueueService _instance =
      OfflineReportQueueService._internal();

  factory OfflineReportQueueService() => _instance;

  static const String _queueKey = 'tb_offline_reports_v1';
  static const int _maxAutomaticRetries = 3;

  final ApiService _api = ApiService();
  final DeviceService _deviceService = DeviceService();
  final DeviceStatusService _statusService = DeviceStatusService();

  bool _isSyncing = false;
  DateTime? _lastSyncAt;

  Future<List<OfflineReportQueueItem>> getQueuedReports() async {
    final queue = await _loadQueue();
    final recovered = queue
        .map((item) => item.state == OfflineReportSyncState.syncing
            ? item.copyWith(state: OfflineReportSyncState.pending)
            : item)
        .toList(growable: false);
    if (!_sameQueue(queue, recovered)) {
      await _saveQueue(recovered);
    }
    recovered.sort((a, b) => b.submittedAtDate.compareTo(a.submittedAtDate));
    return recovered;
  }

  Future<OfflineSubmitResult> submitReport({
    required int incidentTypeId,
    required String incidentTypeName,
    required String description,
    required double latitude,
    required double longitude,
    required double? gpsAccuracy,
    required List<File> evidenceFiles,
    required List<bool> isLiveCapture,
    required List<String> contextTags,
    required String? motionLevel,
    required double? movementSpeed,
    required bool? wasStationary,
    required double? batteryLevel,
  }) async {
    final deviceHash = await _deviceService.getDeviceHash();
    final deviceId = await _deviceService.getDeviceId();
    final currentNetworkType = await _statusService.getNetworkType();
    final submittedAt = DateTime.now();
    final reportId = _generateUuidV4();
    final mediaItems = await _persistEvidenceFiles(
      reportId,
      evidenceFiles,
      isLiveCapture,
      submittedAt,
    );

    final queueItem = OfflineReportQueueItem(
      localReportId: reportId,
      deviceId: deviceId,
      deviceHash: deviceHash,
      incidentTypeId: incidentTypeId,
      incidentTypeName: incidentTypeName,
      description: description,
      latitude: latitude,
      longitude: longitude,
      gpsAccuracy: gpsAccuracy,
      submittedAt: submittedAt.toIso8601String(),
      networkTypeAtSubmit:
          _isOfflineNetwork(currentNetworkType) ? 'Offline' : currentNetworkType!,
      batteryLevel: batteryLevel,
      motionLevel: motionLevel,
      movementSpeed: movementSpeed,
      wasStationary: wasStationary,
      contextTags: contextTags,
      mediaItems: mediaItems,
      state: OfflineReportSyncState.pending,
      retryCount: 0,
      nextRetryAt: null,
      lastError: null,
    );

    final queue = await _loadQueue();
    queue.add(queueItem);
    await _saveQueue(queue);
    AppRefreshBus.notify('offline_queue_saved');

    if (!_isOfflineNetwork(currentNetworkType)) {
      await syncNow(reason: 'submit');
      final remaining = await _findById(reportId);
      return OfflineSubmitResult(
        reportId: reportId,
        queuedOffline: remaining != null,
      );
    }

    return OfflineSubmitResult(reportId: reportId, queuedOffline: true);
  }

  Future<void> retry(String reportId) async {
    final queue = await _loadQueue();
    final updated = queue.map((item) {
      if (item.localReportId != reportId) return item;
      return item.copyWith(
        state: OfflineReportSyncState.pending,
        retryCount: 0,
        nextRetryAt: null,
        lastError: null,
      );
    }).toList(growable: false);
    await _saveQueue(updated);
    AppRefreshBus.notify('offline_queue_retry');
    unawaited(syncNow(reason: 'manual_retry'));
  }

  Future<int> removeItemsSyncedOnServer(Iterable<String> serverReportIds) async {
    final normalizedServerIds = serverReportIds
        .map(_normalizeId)
        .where((id) => id.isNotEmpty)
        .toSet();
    if (normalizedServerIds.isEmpty) return 0;

    final queue = await _loadQueue();
    final originalCount = queue.length;
    queue.removeWhere(
      (item) => normalizedServerIds.contains(_normalizeId(item.localReportId)),
    );

    final removed = originalCount - queue.length;
    if (removed > 0) {
      await _saveQueue(queue);
      AppRefreshBus.notify('offline_queue_deduped');
    }
    return removed;
  }

  Future<void> scheduleSync({String reason = 'manual'}) async {
    if (_isSyncing) return;
    unawaited(syncNow(reason: reason));
  }

  Future<void> syncNow({String reason = 'manual'}) async {
    if (_isSyncing) return;
    if (!await _hasInternet()) return;
    if (_lastSyncAt != null &&
        DateTime.now().difference(_lastSyncAt!) < const Duration(seconds: 2)) {
      return;
    }

    _isSyncing = true;
    _lastSyncAt = DateTime.now();
    try {
      await _recoverInterruptedSyncItems();
      while (true) {
        final next = await _nextEligibleItem();
        if (next == null) break;
        final shouldContinue = await _syncItem(next);
        if (!shouldContinue) break;
      }
    } finally {
      _isSyncing = false;
      AppRefreshBus.notify('offline_queue_sync_complete_$reason');
    }
  }

  Future<void> _recoverInterruptedSyncItems() async {
    final queue = await _loadQueue();
    final recovered = queue
        .map((item) => item.state == OfflineReportSyncState.syncing
            ? item.copyWith(state: OfflineReportSyncState.pending)
            : item)
        .toList(growable: false);
    if (!_sameQueue(queue, recovered)) {
      await _saveQueue(recovered);
    }
  }

  Future<OfflineReportQueueItem?> _nextEligibleItem() async {
    final now = DateTime.now();
    final queue = await _loadQueue();
    queue.sort((a, b) => a.submittedAtDate.compareTo(b.submittedAtDate));
    for (final item in queue) {
      if (item.state == OfflineReportSyncState.syncing) continue;
      if (item.state == OfflineReportSyncState.failed) continue;
      final nextRetryAt = item.nextRetryAtDate;
      if (nextRetryAt != null && nextRetryAt.isAfter(now)) continue;
      return item;
    }
    return null;
  }

  Future<bool> _syncItem(OfflineReportQueueItem item) async {
    await _updateItem(
      item.localReportId,
      (current) => current.copyWith(
        state: OfflineReportSyncState.syncing,
        lastError: null,
        nextRetryAt: null,
      ),
    );
    AppRefreshBus.notify('offline_queue_syncing');

    String? resolvedDeviceId = item.deviceId;
    bool createdThisAttempt = false;

    try {
      final response = await _api.submitReport(_reportPayload(item));
      resolvedDeviceId = response['device_id']?.toString() ?? resolvedDeviceId;
      createdThisAttempt = true;
    } on ApiRequestException catch (e) {
      if (e.statusCode == 409) {
        resolvedDeviceId ??= await _deviceService.ensureDeviceId();
      } else {
        return _handleSyncFailure(item, e.toString());
      }
    } catch (e) {
      return _handleSyncFailure(item, e.toString());
    }

    if (resolvedDeviceId == null || resolvedDeviceId.isEmpty) {
      resolvedDeviceId = await _deviceService.ensureDeviceId();
    }
    if (resolvedDeviceId == null || resolvedDeviceId.isEmpty) {
      return _handleSyncFailure(item, 'Could not resolve device ID for upload.');
    }

    try {
      for (final media in item.mediaItems) {
        final mediaFile = File(media.localPath);
        if (!await mediaFile.exists()) {
          throw Exception('Queued media file is missing.');
        }
        await _api.uploadEvidence(
          item.localReportId,
          resolvedDeviceId,
          media.localPath,
          mediaLatitude: item.latitude,
          mediaLongitude: item.longitude,
          capturedAt: DateTime.tryParse(media.capturedAt),
          isLiveCapture: media.isLiveCapture,
        );
      }
    } catch (e) {
      if (createdThisAttempt) {
        try {
          await _api.deleteReport(item.localReportId, resolvedDeviceId);
        } catch (_) {}
      }
      return _handleSyncFailure(item, e.toString());
    }

    await _removeItem(item.localReportId);
    await _cleanupLocalFiles(item.localReportId);
    AppRefreshBus.notify('offline_queue_sent');
    return await _hasInternet();
  }

  Future<bool> _handleSyncFailure(
    OfflineReportQueueItem item,
    String error,
  ) async {
    final retryCount = item.retryCount + 1;
    final exhausted = retryCount >= _maxAutomaticRetries;
    final nextRetryAt = exhausted
        ? null
        : DateTime.now()
            .add(Duration(seconds: min(60, 5 * retryCount * retryCount)))
            .toIso8601String();

    await _updateItem(
      item.localReportId,
      (current) => current.copyWith(
        deviceId: current.deviceId ?? item.deviceId,
        state: exhausted
            ? OfflineReportSyncState.failed
            : OfflineReportSyncState.pending,
        retryCount: retryCount,
        nextRetryAt: nextRetryAt,
        lastError: error,
      ),
    );
    AppRefreshBus.notify('offline_queue_failed');
    return await _hasInternet();
  }

  Map<String, dynamic> _reportPayload(OfflineReportQueueItem item) {
    return {
      'report_id': item.localReportId,
      if (item.deviceId != null && item.deviceId!.isNotEmpty)
        'device_id': item.deviceId,
      'device_hash': item.deviceHash,
      'incident_type_id': item.incidentTypeId,
      'description': item.description,
      'latitude': item.latitude,
      'longitude': item.longitude,
      'gps_accuracy': item.gpsAccuracy,
      'motion_level': item.motionLevel,
      'movement_speed': item.movementSpeed,
      'was_stationary': item.wasStationary,
      'reported_at': item.submittedAt,
      'context_tags': item.contextTags,
      'network_type': item.networkTypeAtSubmit,
      'battery_level': item.batteryLevel,
    };
  }

  Future<List<OfflineReportMediaItem>> _persistEvidenceFiles(
    String reportId,
    List<File> files,
    List<bool> isLiveCapture,
    DateTime submittedAt,
  ) async {
    final baseDir = await _reportDirectory(reportId);
    await baseDir.create(recursive: true);

    final savedFiles = <OfflineReportMediaItem>[];
    for (int i = 0; i < files.length; i++) {
      final source = files[i];
      final extension = p.extension(source.path);
      final targetPath = p.join(baseDir.path, 'evidence_$i$extension');
      await source.copy(targetPath);
      savedFiles.add(
        OfflineReportMediaItem(
          localPath: targetPath,
          fileType: _inferFileType(source.path),
          isLiveCapture: i < isLiveCapture.length ? isLiveCapture[i] : false,
          capturedAt: submittedAt.toIso8601String(),
        ),
      );
    }
    return savedFiles;
  }

  Future<void> _cleanupLocalFiles(String reportId) async {
    final dir = await _reportDirectory(reportId);
    if (await dir.exists()) {
      await dir.delete(recursive: true);
    }
  }

  Future<Directory> _reportDirectory(String reportId) async {
    final baseDir = await getApplicationDocumentsDirectory();
    return Directory(p.join(baseDir.path, 'offline_reports', reportId));
  }

  Future<List<OfflineReportQueueItem>> _loadQueue() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_queueKey);
    if (raw == null || raw.trim().isEmpty) {
      return <OfflineReportQueueItem>[];
    }

    final decoded = jsonDecode(raw);
    if (decoded is! List) return <OfflineReportQueueItem>[];
    return decoded
        .whereType<Map>()
        .map((item) => OfflineReportQueueItem.fromJson(
              Map<String, dynamic>.from(item),
            ))
        .toList();
  }

  Future<void> _saveQueue(List<OfflineReportQueueItem> queue) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _queueKey,
      jsonEncode(queue.map((item) => item.toJson()).toList(growable: false)),
    );
  }

  Future<void> _updateItem(
    String reportId,
    OfflineReportQueueItem Function(OfflineReportQueueItem current) transform,
  ) async {
    final queue = await _loadQueue();
    final updated = queue.map((item) {
      if (item.localReportId != reportId) return item;
      return transform(item);
    }).toList(growable: false);
    await _saveQueue(updated);
  }

  Future<void> _removeItem(String reportId) async {
    final queue = await _loadQueue();
    queue.removeWhere((item) => item.localReportId == reportId);
    await _saveQueue(queue);
  }

  Future<OfflineReportQueueItem?> _findById(String reportId) async {
    final queue = await _loadQueue();
    for (final item in queue) {
      if (item.localReportId == reportId) return item;
    }
    return null;
  }

  Future<bool> _hasInternet() async {
    final connectivity = await Connectivity().checkConnectivity();
    return !connectivity.contains(ConnectivityResult.none);
  }

  bool _sameQueue(
    List<OfflineReportQueueItem> a,
    List<OfflineReportQueueItem> b,
  ) {
    if (a.length != b.length) return false;
    for (int i = 0; i < a.length; i++) {
      if (jsonEncode(a[i].toJson()) != jsonEncode(b[i].toJson())) return false;
    }
    return true;
  }

  bool _isOfflineNetwork(String? networkType) {
    return networkType == null ||
        networkType.trim().isEmpty ||
        networkType.toLowerCase() == 'none' ||
        networkType.toLowerCase() == 'offline';
  }

  String _inferFileType(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.mp4') ||
        lower.endsWith('.mov') ||
        lower.endsWith('.avi') ||
        lower.endsWith('.mkv')) {
      return 'video';
    }
    return 'photo';
  }

  String _generateUuidV4() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;

    String hex(int value) => value.toRadixString(16).padLeft(2, '0');

    return [
      for (int i = 0; i < bytes.length; i++) hex(bytes[i]),
    ].join().replaceFirstMapped(
          RegExp(r'^(.{8})(.{4})(.{4})(.{4})(.{12})$'),
          (m) => '${m[1]}-${m[2]}-${m[3]}-${m[4]}-${m[5]}',
        );
  }

  String _normalizeId(String value) {
    return value.trim().toLowerCase();
  }
}
