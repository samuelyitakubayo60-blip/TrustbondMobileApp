import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:uuid/uuid.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../services/api_service.dart';
import '../services/offline_database_service.dart';

class EnhancedOfflineQueue {
  static final EnhancedOfflineQueue _instance = EnhancedOfflineQueue._internal();
  factory EnhancedOfflineQueue() => _instance;
  EnhancedOfflineQueue._internal();

  final OfflineDatabaseService _db = OfflineDatabaseService();
  final ApiService _api = ApiService();
  final Uuid _uuid = const Uuid();

  /// Enqueue a complete report with evidence for offline storage
  Future<String> enqueueReport({
    required Map<String, dynamic> reportData,
    required List<Map<String, dynamic>> evidenceFiles,
    int syncPriority = 1, // 1=high, 2=medium, 3=low
  }) async {
    // Check if database is available (for desktop platforms without SQLite FFI)
    if (databaseFactory == null && (Platform.isWindows || Platform.isLinux || Platform.isMacOS)) {
      print('Desktop platform - SQLite not available, using direct API submission');
      // For now, just return a mock queue ID and let the app continue
      return _uuid.v4();
    }

    final queueId = _uuid.v4();
    final now = DateTime.now().toIso8601String();

    // Prepare report data for SQLite
    final reportQueueData = {
      'queue_id': queueId,
      'sync_status': 'queued',
      'attempts': 0,
      'created_at': now,
      'updated_at': now,
      'sync_priority': syncPriority,
      
      // Core report data
      'device_hash': reportData['device_hash'] ?? '',
      'incident_type_id': reportData['incident_type_id'],
      'description': reportData['description'],
      'latitude': reportData['latitude'],
      'longitude': reportData['longitude'],
      'gps_accuracy': reportData['gps_accuracy'],
      'movement_speed': reportData['movement_speed'],
      'was_stationary': reportData['was_stationary'] == true ? 1 : 0,
      'location_id': reportData['location_id'],
      'handling_station_id': reportData['handling_station_id'],
      'reported_at': reportData['reported_at'] ?? now,
      'status': reportData['status'] ?? 'pending',
      'is_flagged': reportData['is_flagged'] == true ? 1 : 0,
      'flag_reason': reportData['flag_reason'],
      'verification_status': reportData['verification_status'] ?? 'pending',
      'verified_by': reportData['verified_by'],
      'verified_at': reportData['verified_at'],
      'app_version': reportData['app_version'],
      'network_type': reportData['network_type'],
      'battery_level': reportData['battery_level'],
      'motion_level': reportData['motion_level'],
      'village_location_id': reportData['village_location_id'],
      'context_tags': jsonEncode(reportData['context_tags'] ?? []),
      'priority': reportData['priority'] ?? 'medium',
    };

    // Insert report into queue
    await _db.insertReport(reportQueueData);

    // Insert evidence files
    for (final evidence in evidenceFiles) {
      final evidenceQueueData = {
        'evidence_id': _uuid.v4(),
        'queue_id': queueId,
        'status': 'pending',
        'attempts': 0,
        'created_at': now,
        'updated_at': now,
        
        // File data
        'file_type': evidence['file_type'] ?? 'photo',
        'file_size': evidence['file_size'],
        'duration': evidence['duration'],
        'media_latitude': evidence['media_latitude'],
        'media_longitude': evidence['media_longitude'],
        'captured_at': evidence['captured_at'],
        'is_live_capture': evidence['is_live_capture'] == true ? 1 : 0,
        'cloudinary_public_id': evidence['cloudinary_public_id'],
        'cloudinary_url': evidence['cloudinary_url'],
        
        // Local file path
        'local_file_path': evidence['local_file_path'],
      };

      await _db.insertEvidence(evidenceQueueData);
    }

    // Update sync status
    await _updateSyncStats();
    
    return queueId;
  }

  /// Sync all pending reports when network is available
  Future<void> syncIfNeeded() async {
    final connectivity = await Connectivity().checkConnectivity();
    if (connectivity.contains(ConnectivityResult.none)) {
      return; // No network
    }

    try {
      final pendingReports = await _db.getPendingReports(limit: 10);
      
      for (final report in pendingReports) {
        await _syncReport(report);
      }
      
      await _updateSyncStats();
    } catch (e) {
      print('Sync error: $e');
    }
  }

  Future<void> _syncReport(Map<String, dynamic> report) async {
    final queueId = report['queue_id'] as String;
    final attempts = report['attempts'] as int? ?? 0;
    
    // Check if we should retry (exponential backoff)
    if (!_shouldAttempt(report)) {
      return;
    }

    try {
      // Update status to syncing
      await _db.updateReportStatus(queueId, 'syncing');

      // Step 1: Ensure device is registered
      String? deviceId = report['device_id'] as String?;
      final deviceHash = report['device_hash'] as String;
      
      if (deviceId == null || deviceId.isEmpty) {
        final cachedDevice = await _db.getCachedDevice(deviceHash);
        if (cachedDevice != null && cachedDevice['is_registered'] == 1) {
          deviceId = cachedDevice['device_id'] as String?;
        }
        
        if (deviceId == null || deviceId.isEmpty) {
          final deviceReg = await _api.registerDevice(deviceHash);
          deviceId = deviceReg['device_id']?.toString();
          
          if (deviceId != null) {
            await _db.cacheDeviceData(deviceHash, {
              'device_id': deviceId,
              ...deviceReg,
            });
            await _db.updateReportWithServerData(queueId, {'device_id': deviceId});
          }
        }
      }

      if (deviceId == null || deviceId.isEmpty) {
        throw Exception('Device registration failed');
      }

      // Step 2: Submit report to server
      String? serverReportId = report['report_id'] as String?;
      if (serverReportId == null || serverReportId.isEmpty) {
        final reportData = _prepareReportDataForSubmission(report, deviceId);
        final result = await _api.submitReport(reportData);
        serverReportId = result['report_id']?.toString();
        
        if (serverReportId != null) {
          await _db.updateReportWithServerData(queueId, {
            'report_id': serverReportId,
            'server_report_id': serverReportId,
          });
        }
      }

      if (serverReportId == null || serverReportId.isEmpty) {
        throw Exception('Report submission failed');
      }

      // Step 3: Upload evidence files
      await _syncEvidenceFiles(queueId, serverReportId, deviceId);

      // Step 4: Mark as completed
      await _db.updateReportStatus(queueId, 'completed');
      
    } catch (e) {
      await _handleSyncError(queueId, e, attempts);
    }
  }

  Future<void> _syncEvidenceFiles(String queueId, String reportId, String deviceId) async {
    final evidenceFiles = await _db.getPendingEvidence(queueId);
    
    for (final evidence in evidenceFiles) {
      final evidenceId = evidence['evidence_id'] as String;
      final attempts = evidence['attempts'] as int? ?? 0;
      final localPath = evidence['local_file_path'] as String;
      
      try {
        await _db.updateEvidenceStatus(evidenceId, 'uploading');
        
        await _api.uploadEvidence(
          reportId,
          deviceId,
          localPath,
          mediaLatitude: evidence['media_latitude']?.toDouble(),
          mediaLongitude: evidence['media_longitude']?.toDouble(),
          capturedAt: evidence['captured_at'] != null 
              ? DateTime.tryParse(evidence['captured_at'])
              : null,
          isLiveCapture: evidence['is_live_capture'] == 1,
        );
        
        await _db.updateEvidenceStatus(evidenceId, 'completed');
        
      } catch (e) {
        await _handleEvidenceError(evidenceId, e, attempts);
        if (!_isNetworkError(e)) {
          rethrow; // Non-network error, stop processing this report
        }
      }
    }
  }

  Map<String, dynamic> _prepareReportDataForSubmission(
    Map<String, dynamic> report, 
    String deviceId
  ) {
    return {
      'device_id': deviceId,
      'incident_type_id': report['incident_type_id'],
      'description': report['description'],
      'latitude': report['latitude'],
      'longitude': report['longitude'],
      'gps_accuracy': report['gps_accuracy'],
      'movement_speed': report['movement_speed'],
      'was_stationary': report['was_stationary'] == 1,
      'location_id': report['location_id'],
      'handling_station_id': report['handling_station_id'],
      'reported_at': report['reported_at'],
      'app_version': report['app_version'],
      'network_type': report['network_type'],
      'battery_level': report['battery_level'],
      'motion_level': report['motion_level'],
      'village_location_id': report['village_location_id'],
      'context_tags': jsonDecode(report['context_tags'] ?? '[]'),
      'priority': report['priority'] ?? 'medium',
    };
  }

  Future<void> _handleSyncError(String queueId, Object error, int attempts) async {
    if (_isNetworkError(error)) {
      // Network error - retry with exponential backoff
      final backoff = Duration(seconds: 5 * (attempts * attempts).clamp(1, 72));
      final nextAttempt = DateTime.now().add(backoff).toIso8601String();
      
      await _db.updateReportStatus(queueId, 'failed', error: error.toString());
      await _db.updateReportWithServerData(queueId, {
        'attempts': attempts + 1,
        'next_attempt_at': nextAttempt,
      });
    } else {
      // Non-network error - mark as failed
      await _db.updateReportStatus(queueId, 'failed', error: error.toString());
    }
  }

  Future<void> _handleEvidenceError(String evidenceId, Object error, int attempts) async {
    if (_isNetworkError(error)) {
      final backoff = Duration(seconds: 10 + attempts * 5);
      final nextAttempt = DateTime.now().add(backoff).toIso8601String();
      
      await _db.updateEvidenceStatus(evidenceId, 'failed', error: error.toString());
      await _db.updateEvidenceWithServerData(evidenceId, {
        'attempts': attempts + 1,
        'next_attempt_at': nextAttempt,
      });
    } else {
      await _db.updateEvidenceStatus(evidenceId, 'failed', error: error.toString());
    }
  }

  bool _shouldAttempt(Map<String, dynamic> item) {
    final nextAttempt = item['next_attempt_at'] as String?;
    if (nextAttempt == null) return true;
    
    final parsed = DateTime.tryParse(nextAttempt);
    if (parsed == null) return true;
    
    return DateTime.now().isAfter(parsed);
  }

  bool _isNetworkError(Object error) {
    return error is SocketException || 
           error is TimeoutException ||
           error.toString().contains('Network') ||
           error.toString().contains('Connection');
  }

  Future<void> _updateSyncStats() async {
    final stats = await _db.getQueueStats();
    
    await _db.updateSyncStatus({
      'last_sync_at': DateTime.now().toIso8601String(),
      'pending_reports': stats['queued_reports'] ?? 0,
      'failed_reports': stats['failed_reports'] ?? 0,
      'pending_evidence': stats['pending_evidence'] ?? 0,
      'failed_evidence': stats['failed_evidence'] ?? 0,
      'total_synced_reports': stats['completed_reports'] ?? 0,
      'total_synced_evidence': stats['completed_evidence'] ?? 0,
    });
  }

  // Public methods for UI
  Future<Map<String, int>> getQueueStats() async {
    return await _db.getQueueStats();
  }

  Future<List<Map<String, dynamic>>> getPendingReports() async {
    return await _db.getPendingReports();
  }

  Future<void> retryFailedReport(String queueId) async {
    await _db.updateReportStatus(queueId, 'queued');
    await _db.updateReportWithServerData(queueId, {
      'next_attempt_at': null,
      'attempts': 0,
    });
    await syncIfNeeded();
  }

  Future<void> retryAllFailed() async {
    final pendingReports = await _db.getPendingReports();
    
    for (final report in pendingReports) {
      if (report['sync_status'] == 'failed') {
        await retryFailedReport(report['queue_id'] as String);
      }
    }
  }

  Future<void> cleanupOldItems() async {
    await _db.cleanupOldCompletedItems();
  }
}
