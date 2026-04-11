/// Integration Guide for Enhanced Offline Reporting System
/// 
/// This file shows how to integrate the new SQLite-based offline queue
/// with your existing TrustBond reporting functionality.

import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'enhanced_offline_queue.dart';
import 'background_sync_service.dart';
import 'offline_database_service.dart';

class OfflineReportingIntegration {
  static final OfflineReportingIntegration _instance = OfflineReportingIntegration._internal();
  factory OfflineReportingIntegration() => _instance;
  OfflineReportingIntegration._internal();

  final EnhancedOfflineQueue _queue = EnhancedOfflineQueue();
  final BackgroundSyncService _sync = BackgroundSyncService();

  /// Initialize the offline reporting system
  /// Call this in your main.dart or app initialization
  Future<void> initialize() async {
    try {
      // Check if databaseFactory is available before attempting database operations
      if (databaseFactory == null && (Platform.isWindows || Platform.isLinux || Platform.isMacOS)) {
        print('Desktop platform detected - SQLite FFI not available, using online-only mode');
        // Start background sync only (without database)
        await _sync.start();
        return;
      }
      
      // Initialize database for platforms with SQLite support
      await OfflineDatabaseService().database;
      
      // Start background sync service
      await _sync.start();
      
      print('Offline reporting system initialized successfully');
    } catch (e) {
      print('Failed to initialize offline reporting: $e');
      // Don't rethrow - allow app to continue without offline features
    }
  }

  /// Create and enqueue a report with evidence (offline-first)
  /// Replace your existing report submission logic with this
  Future<String> submitReportOffline({
    required String deviceHash,
    required int incidentTypeId,
    required String description,
    required double latitude,
    required double longitude,
    required List<File> evidenceFiles,
    // Optional metadata
    double? gpsAccuracy,
    double? movementSpeed,
    bool? wasStationary,
    int? locationId,
    int? handlingStationId,
    String? appVersion,
    String? networkType,
    double? batteryLevel,
    String? motionLevel,
    int? villageLocationId,
    List<String>? contextTags,
    String priority = 'medium',
  }) async {
    // Prepare report data
    final reportData = {
      'device_hash': deviceHash,
      'incident_type_id': incidentTypeId,
      'description': description,
      'latitude': latitude,
      'longitude': longitude,
      'gps_accuracy': gpsAccuracy,
      'movement_speed': movementSpeed,
      'was_stationary': wasStationary,
      'location_id': locationId,
      'handling_station_id': handlingStationId,
      'reported_at': DateTime.now().toIso8601String(),
      'app_version': appVersion,
      'network_type': networkType,
      'battery_level': batteryLevel,
      'motion_level': motionLevel,
      'village_location_id': villageLocationId,
      'context_tags': contextTags ?? [],
      'priority': priority,
    };

    // Prepare evidence files
    final evidenceData = evidenceFiles.map((file) {
      return {
        'local_file_path': file.path,
        'file_type': file.path.toLowerCase().endsWith('.mp4') ? 'video' : 'photo',
        'file_size': file.lengthSync(),
        'captured_at': DateTime.now().toIso8601String(),
        'is_live_capture': false, // Set based on your capture logic
      };
    }).toList();

    // Determine sync priority (reports with evidence = high priority)
    final syncPriority = evidenceFiles.isNotEmpty ? 1 : 2;

    // Enqueue for offline storage and sync
    final queueId = await _queue.enqueueReport(
      reportData: reportData,
      evidenceFiles: evidenceData,
      syncPriority: syncPriority,
    );

    return queueId;
  }

  /// Get current queue status for UI indicators
  Future<OfflineQueueStatus> getQueueStatus() async {
    final stats = await _queue.getQueueStats();
    final syncStatus = await _sync.getSyncStatus();
    
    return OfflineQueueStatus(
      pendingReports: stats['queued_reports'] ?? 0,
      failedReports: stats['failed_reports'] ?? 0,
      pendingEvidence: stats['pending_evidence'] ?? 0,
      failedEvidence: stats['failed_evidence'] ?? 0,
      isSyncing: syncStatus?['is_syncing'] ?? false,
      lastSyncAt: syncStatus?['last_sync_at'],
      networkStatus: syncStatus?['network_status'] ?? 'unknown',
    );
  }

  /// Retry failed reports
  Future<void> retryFailedReports() async {
    await _queue.retryAllFailed();
  }

  /// Manual sync trigger
  Future<void> syncNow() async {
    await _sync.syncNow();
  }

  /// Cleanup old completed items
  Future<void> cleanup() async {
    await _queue.cleanupOldItems();
  }
}

/// Data model for queue status
class OfflineQueueStatus {
  final int pendingReports;
  final int failedReports;
  final int pendingEvidence;
  final int failedEvidence;
  final bool isSyncing;
  final String? lastSyncAt;
  final String networkStatus;

  const OfflineQueueStatus({
    required this.pendingReports,
    required this.failedReports,
    required this.pendingEvidence,
    required this.failedEvidence,
    required this.isSyncing,
    this.lastSyncAt,
    required this.networkStatus,
  });

  bool get hasPendingItems => pendingReports > 0 || pendingEvidence > 0;
  bool get hasFailedItems => failedReports > 0 || failedEvidence > 0;
  int get totalPending => pendingReports + pendingEvidence;
  int get totalFailed => failedReports + failedEvidence;
}

/// Example UI Widget for sync status
class SyncStatusWidget extends StatefulWidget {
  const SyncStatusWidget({super.key});

  @override
  State<SyncStatusWidget> createState() => _SyncStatusWidgetState();
}

class _SyncStatusWidgetState extends State<SyncStatusWidget> {
  final OfflineReportingIntegration _offline = OfflineReportingIntegration();
  OfflineQueueStatus? _status;
  Timer? _refreshTimer;

  @override
  void initState() {
    super.initState();
    _refreshStatus();
    _refreshTimer = Timer.periodic(const Duration(seconds: 5), (_) => _refreshStatus());
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    super.dispose();
  }

  Future<void> _refreshStatus() async {
    final status = await _offline.getQueueStatus();
    if (mounted) {
      setState(() {
        _status = status;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_status == null) {
      return const CircularProgressIndicator();
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  _getStatusIcon(_status!.networkStatus),
                  color: _getStatusColor(_status!.networkStatus),
                ),
                const SizedBox(width: 8),
                Text(
                  _getStatusText(_status!),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                if (_status!.isSyncing) ...[
                  const SizedBox(width: 8),
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ],
              ],
            ),
            if (_status!.hasPendingItems) ...[
              const SizedBox(height: 8),
              Text('${_status!.totalPending} items pending sync'),
            ],
            if (_status!.hasFailedItems) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  Text('${_status!.totalFailed} items failed'),
                  const SizedBox(width: 8),
                  TextButton(
                    onPressed: () => _offline.retryFailedReports(),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 8),
            Row(
              children: [
                TextButton(
                  onPressed: () => _offline.syncNow(),
                  child: const Text('Sync Now'),
                ),
                TextButton(
                  onPressed: () => _offline.cleanup(),
                  child: const Text('Cleanup'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  IconData _getStatusIcon(String status) {
    switch (status) {
      case 'online':
        return Icons.cloud_done;
      case 'offline':
        return Icons.cloud_off;
      case 'syncing':
        return Icons.sync;
      case 'error':
        return Icons.error;
      default:
        return Icons.cloud_queue;
    }
  }

  Color _getStatusColor(String status) {
    switch (status) {
      case 'online':
        return Colors.green;
      case 'offline':
        return Colors.grey;
      case 'syncing':
        return Colors.blue;
      case 'error':
        return Colors.red;
      default:
        return Colors.grey;
    }
  }

  String _getStatusText(OfflineQueueStatus status) {
    if (status.isSyncing) return 'Syncing...';
    switch (status.networkStatus) {
      case 'online':
        return 'Online';
      case 'offline':
        return 'Offline';
      case 'error':
        return 'Sync Error';
      default:
        return 'Unknown';
    }
  }
}

/// Migration from old SharedPreferences system:
/// 
/// 1. Replace OfflineReportQueue() with EnhancedOfflineQueue()
/// 2. Replace SharedPreferences calls with OfflineDatabaseService()
/// 3. Initialize the system in main.dart:
/// 
/// ```dart
/// void main() async {
///   WidgetsFlutterBinding.ensureInitialized();
///   await OfflineReportingIntegration().initialize();
///   runApp(MyApp());
/// }
/// ```
/// 
/// 4. Update your report submission to use submitReportOffline()
/// 5. Add SyncStatusWidget to your UI for user feedback
/// 
/// The new system automatically handles:
/// - SQLite storage instead of SharedPreferences
/// - Background sync when network is available
/// - Priority-based processing (evidence files first)
/// - Exponential backoff retry logic
/// - Automatic cleanup of old completed items
/// - Real-time sync status updates
