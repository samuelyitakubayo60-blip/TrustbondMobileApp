import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../services/api_service.dart';

class OfflineReportQueue {
  static final OfflineReportQueue _instance = OfflineReportQueue._internal();
  factory OfflineReportQueue() => _instance;
  OfflineReportQueue._internal();

  static const String _prefsKey = 'tb_offline_report_queue_v1';
  final Uuid _uuid = const Uuid();

  Future<List<Map<String, dynamic>>> _loadQueue() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_prefsKey);
    if (raw == null || raw.trim().isEmpty) return [];

    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return [];
      return decoded
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList(growable: true);
    } catch (_) {
      return [];
    }
  }

  Future<void> _saveQueue(List<Map<String, dynamic>> items) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, jsonEncode(items));
  }

  Map<String, dynamic> _sanitizeReportData(Map<String, dynamic> reportData) {
    // Ensure we only keep JSON-safe values in the queue.
    // (Backend expects numeric/bool/string; we keep those as-is.)
    final out = <String, dynamic>{};
    reportData.forEach((k, v) {
      if (v == null) return;
      if (v is num || v is bool || v is String) {
        out[k] = v;
        return;
      }
      // Convert other types (e.g., enums) to string defensively.
      out[k] = v.toString();
    });
    return out;
  }

  DateTime _now() => DateTime.now().toUtc();

  bool _isJsonLoadedSuccessfully(Map<String, dynamic> item) {
    return item.containsKey('queue_id') && item.containsKey('report_data');
  }

  /// Enqueue a report submission + evidence uploads to be retried later.
  /// If [reportId]/[deviceId] are provided, sync will skip submitReport().
  Future<String> enqueue({
    required Map<String, dynamic> reportData,
    required List<Map<String, dynamic>> evidenceFiles,
    String? reportId,
    String? deviceId,
  }) async {
    final queueId = _uuid.v4();
    final now = _now();

    final sanitizedReportData = _sanitizeReportData(reportData);
    final sanitizedEvidence = evidenceFiles.map((e) {
      return <String, dynamic>{
        'path': e['path']?.toString() ?? '',
        'type': e['type']?.toString() ?? 'photo',
        'is_live_capture': (e['is_live_capture'] == true),
        'captured_at': e['captured_at']?.toString(),
        'uploaded': e['uploaded'] == true,
        'attempts': (e['attempts'] is int) ? e['attempts'] : 0,
      };
    }).toList(growable: false);

    final item = <String, dynamic>{
      'queue_id': queueId,
      'created_at': now.toIso8601String(),
      'status': 'queued',
      'attempts': 0,
      'next_attempt_at': null,
      'report_id': reportId,
      'device_id': deviceId,
      'report_data': sanitizedReportData,
      'evidence_files': sanitizedEvidence,
    };

    final items = await _loadQueue();
    items.add(item);
    await _saveQueue(items);
    return queueId;
  }

  Future<bool> _shouldAttempt(Map<String, dynamic> item) async {
    final next = item['next_attempt_at'];
    if (next == null) return true;
    final parsed = DateTime.tryParse(next.toString());
    if (parsed == null) return true;
    return _now().isAfter(parsed);
  }

  bool _isNetworkError(Object e) {
    return e is SocketException || e is TimeoutException;
  }

  bool _looksLikeServer500(Object e) {
    final msg = e.toString().toLowerCase();
    return msg.contains('http 500') ||
        msg.contains('(500)') ||
        msg.contains('status 500') ||
        msg.contains('internal server error');
  }

  bool _looksLikeAlreadyUploadedError(Object e) {
    final msg = e.toString().toLowerCase();
    final hasAlready = msg.contains('already');
    final hasDuplicate = msg.contains('duplicate') || msg.contains('exists');
    final hasEvidenceHint = msg.contains('evidence') || msg.contains('upload');
    return (hasAlready || hasDuplicate) && hasEvidenceHint;
  }

  Future<Map<String, String>?> _recoverSubmittedReport({
    required ApiService api,
    required Map<String, dynamic> reportData,
    String? deviceId,
  }) async {
    var resolvedDeviceId = deviceId;
    if (resolvedDeviceId == null || resolvedDeviceId.isEmpty) {
      final deviceHash = reportData['device_hash']?.toString();
      if (deviceHash != null && deviceHash.isNotEmpty) {
        try {
          final reg = await api
              .registerDevice(deviceHash)
              .timeout(const Duration(seconds: 2));
          resolvedDeviceId = reg['device_id']?.toString();
        } catch (_) {}
      }
    }

    if (resolvedDeviceId == null || resolvedDeviceId.isEmpty) {
      return null;
    }

    final list = await api
        .getMyReports(resolvedDeviceId)
        .timeout(const Duration(seconds: 8));

    final expectedType = reportData['incident_type_id'] is num
        ? (reportData['incident_type_id'] as num).toInt()
        : null;
    final expectedDesc = (reportData['description']?.toString() ?? '').trim();
    final expectedLat = reportData['latitude'] is num
        ? (reportData['latitude'] as num).toDouble()
        : null;
    final expectedLng = reportData['longitude'] is num
        ? (reportData['longitude'] as num).toDouble()
        : null;
    final now = DateTime.now().toUtc();

    for (final raw in list.take(20)) {
      if (raw is! Map) continue;
      final m = Map<String, dynamic>.from(raw);
      final reportId = m['report_id']?.toString();
      if (reportId == null || reportId.isEmpty) continue;

      final reportedAt = DateTime.tryParse(m['reported_at']?.toString() ?? '')?.toUtc();
      if (reportedAt == null) continue;
      if (now.difference(reportedAt).inMinutes > 15) continue;

      final type = m['incident_type_id'] is num
          ? (m['incident_type_id'] as num).toInt()
          : null;
      if (expectedType != null && type != expectedType) continue;

      final desc = (m['description']?.toString() ?? '').trim();
      if (expectedDesc.isNotEmpty && desc != expectedDesc) continue;

      final lat = m['latitude'] is num ? (m['latitude'] as num).toDouble() : null;
      final lng = m['longitude'] is num ? (m['longitude'] as num).toDouble() : null;
      if (expectedLat != null && lat != null && (expectedLat - lat).abs() > 0.0005) continue;
      if (expectedLng != null && lng != null && (expectedLng - lng).abs() > 0.0005) continue;

      return {
        'report_id': reportId,
        'device_id': m['device_id']?.toString() ?? resolvedDeviceId,
      };
    }

    return null;
  }

  /// Returns queue items that are still pending or failed.
  Future<List<OfflineQueueItem>> getPendingItems() async {
    final items = await _loadQueue();
    return items
        .where((e) {
          final status = (e['status'] ?? '').toString();
          return status == 'queued' || status == 'error';
        })
        .map((e) => OfflineQueueItem(
              queueId: (e['queue_id'] ?? '').toString(),
              status: (e['status'] ?? 'queued').toString(),
              reportId: e['report_id']?.toString(),
              attempts: e['attempts'] is int ? e['attempts'] as int : 0,
              error: e['error']?.toString(),
              evidenceCount: (e['evidence_files'] is List)
                  ? (e['evidence_files'] as List).length
                  : 0,
              createdAt: DateTime.tryParse((e['created_at'] ?? '').toString()),
              nextAttemptAt:
                  DateTime.tryParse((e['next_attempt_at'] ?? '').toString()),
            ))
        .toList(growable: false);
  }

  /// Manual retry for all failed items.
  Future<void> retryAllFailedNow() async {
    final items = await _loadQueue();
    bool changed = false;
    for (final item in items) {
      final status = (item['status'] ?? '').toString();
      if (status == 'error') {
        item['status'] = 'queued';
        item['next_attempt_at'] = null;
        changed = true;
      }
    }
    if (changed) {
      await _saveQueue(items);
    }
    await syncIfNeeded();
  }

  /// Manual retry for a specific queue entry.
  Future<void> retryNow(String queueId) async {
    if (queueId.trim().isEmpty) return;
    final items = await _loadQueue();
    bool changed = false;
    for (final item in items) {
      if ((item['queue_id'] ?? '').toString() == queueId) {
        item['status'] = 'queued';
        item['next_attempt_at'] = null;
        changed = true;
        break;
      }
    }
    if (changed) {
      await _saveQueue(items);
    }
    await syncIfNeeded();
  }

  /// Read-only stats for UI badges/indicators.
  Future<OfflineQueueStats> getStats() async {
    final items = await _loadQueue();
    var queued = 0;
    var errors = 0;
    for (final item in items) {
      final status = (item['status'] ?? '').toString();
      if (status == 'queued') queued++;
      if (status == 'error') errors++;
    }
    return OfflineQueueStats(queuedCount: queued, errorCount: errors);
  }

  /// Sync pending items. Safe to call frequently.
  Future<void> syncIfNeeded() async {
    final connectivity = await Connectivity().checkConnectivity();
    final isOffline = connectivity.contains(ConnectivityResult.none);
    if (isOffline) return;

    final items = await _loadQueue();
    if (items.isEmpty) return;

    bool changed = false;
    final api = ApiService();

    for (final item in items) {
      if (!_isJsonLoadedSuccessfully(item)) continue;
      final status = (item['status'] ?? '').toString();
      if (status != 'queued' && status != 'error') continue;
      if (!await _shouldAttempt(item)) continue;

      // Give failed entries another chance on next scheduled retry.
      if (status == 'error') {
        item['status'] = 'queued';
        item.remove('error');
        changed = true;
      }

      final reportData = (item['report_data'] is Map<String, dynamic>)
          ? item['report_data'] as Map<String, dynamic>
          : <String, dynamic>{};

      final evidenceFiles = (item['evidence_files'] is List)
          ? (item['evidence_files'] as List)
              .whereType<Map<String, dynamic>>()
              .toList(growable: false)
          : <Map<String, dynamic>>[];

      final reportId = item['report_id']?.toString();
      var deviceId = item['device_id']?.toString();

      // 1) If we don't have a report_id yet, submit it now.
      String? resolvedReportId = reportId;
      if (resolvedReportId == null || resolvedReportId.isEmpty) {
        try {
          final result = await api.submitReport(reportData);
          resolvedReportId = result['report_id']?.toString();
          deviceId = result['device_id']?.toString() ?? deviceId;

          if (resolvedReportId == null || resolvedReportId.isEmpty) {
            // Backend didn't return what we need; retry later.
            item['attempts'] = (item['attempts'] is int ? item['attempts'] : 0) + 1;
            item['next_attempt_at'] = _now().toIso8601String();
            changed = true;
            continue;
          }

          item['report_id'] = resolvedReportId;
          item['device_id'] = deviceId;
          changed = true;
        } catch (e) {
          if (_isNetworkError(e)) {
            item['attempts'] = (item['attempts'] is int ? item['attempts'] : 0) + 1;
            final attempts = item['attempts'] as int;
            // Exponential-ish backoff, capped.
            final backoff = Duration(seconds: 5 * (attempts * attempts).clamp(1, 72));
            item['next_attempt_at'] = _now().add(backoff).toIso8601String();
            changed = true;
            continue;
          }

          var recoveredFrom500 = false;
          if (_looksLikeServer500(e)) {
            try {
              final recovered = await _recoverSubmittedReport(
                api: api,
                reportData: reportData,
                deviceId: deviceId,
              );
              if (recovered != null) {
                resolvedReportId = recovered['report_id'];
                deviceId = recovered['device_id'];
                item['report_id'] = resolvedReportId;
                item['device_id'] = deviceId;
                item['status'] = 'queued';
                item.remove('error');
                item['next_attempt_at'] = null;
                changed = true;
                recoveredFrom500 = true;
              }
            } catch (_) {}
          }

          if (recoveredFrom500) {
            // Continue to evidence upload step below.
          } else {
            // Non-network failure; mark error and stop retrying.
            item['status'] = 'error';
            item['error'] = e.toString();
            changed = true;
            continue;
          }
        }
      }

      // 2) Upload remaining evidence.
      if (deviceId == null || deviceId.isEmpty || resolvedReportId == null || resolvedReportId.isEmpty) {
        // Can't upload evidence without device_id.
        item['attempts'] = (item['attempts'] is int ? item['attempts'] : 0) + 1;
        item['next_attempt_at'] = _now().toIso8601String();
        item['status'] = 'queued';
        changed = true;
        continue;
      }

      bool allUploaded = true;
      for (final ef in evidenceFiles) {
        final uploaded = ef['uploaded'] == true;
        if (uploaded) continue;
        allUploaded = false;

        final path = ef['path']?.toString() ?? '';
        if (path.isEmpty) {
          ef['attempts'] = (ef['attempts'] is int ? ef['attempts'] : 0) + 1;
          continue;
        }

        try {
          final lat = reportData['latitude'];
          final lon = reportData['longitude'];
          final capturedRaw = ef['captured_at']?.toString();
          final capturedAt = capturedRaw == null
              ? DateTime.now().toUtc()
              : DateTime.tryParse(capturedRaw)?.toUtc() ?? DateTime.now().toUtc();

          await api.uploadEvidence(
            resolvedReportId,
            deviceId,
            path,
            mediaLatitude: lat is num ? lat.toDouble() : null,
            mediaLongitude: lon is num ? lon.toDouble() : null,
            capturedAt: capturedAt,
            isLiveCapture: ef['is_live_capture'] == true,
          );

          ef['uploaded'] = true;
          changed = true;
        } catch (e) {
          if (_isNetworkError(e)) {
            ef['attempts'] = (ef['attempts'] is int ? ef['attempts'] : 0) + 1;
            // Stop processing this item; retry later.
            final attempts = item['attempts'] as int? ?? 0;
            final backoff = Duration(seconds: 10 + attempts * 5);
            item['next_attempt_at'] = _now().add(backoff).toIso8601String();
            changed = true;
            allUploaded = false;
            break;
          }

          if (_looksLikeAlreadyUploadedError(e)) {
            ef['uploaded'] = true;
            changed = true;
            continue;
          }

          // Non-network evidence failure; mark item error.
          item['status'] = 'error';
          item['error'] = 'Evidence upload failed for ${ef['path']}: ${e.toString()}';
          changed = true;
          allUploaded = false;
          break;
        }
      }

      // 3) If everything is uploaded, mark done (and remove on next save).
      if (allUploaded) {
        item['status'] = 'done';
        changed = true;
      }
    }

    if (!changed) return;

    // Remove done items to keep storage small.
    final updated = items.where((i) => i['status'] != 'done').toList(growable: false);
    await _saveQueue(updated);
  }
}

class OfflineQueueItem {
  final String queueId;
  final String status;
  final String? reportId;
  final int attempts;
  final String? error;
  final int evidenceCount;
  final DateTime? createdAt;
  final DateTime? nextAttemptAt;

  const OfflineQueueItem({
    required this.queueId,
    required this.status,
    required this.reportId,
    required this.attempts,
    required this.error,
    required this.evidenceCount,
    required this.createdAt,
    required this.nextAttemptAt,
  });
}

class OfflineQueueStats {
  final int queuedCount;
  final int errorCount;

  const OfflineQueueStats({
    required this.queuedCount,
    required this.errorCount,
  });

  int get totalCount => queuedCount + errorCount;
  bool get hasPendingSync => queuedCount > 0;
}

