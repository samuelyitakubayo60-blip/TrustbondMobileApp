import 'dart:async';
import 'dart:io';
import 'dart:isolate';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';

import 'enhanced_offline_queue.dart';
import 'offline_database_service.dart';

class BackgroundSyncService {
  static final BackgroundSyncService _instance = BackgroundSyncService._internal();
  factory BackgroundSyncService() => _instance;
  BackgroundSyncService._internal();

  final EnhancedOfflineQueue _queue = EnhancedOfflineQueue();
  final OfflineDatabaseService _db = OfflineDatabaseService();

  Timer? _periodicSyncTimer;
  Timer? _cleanupTimer;
  StreamSubscription<List<ConnectivityResult>>? _networkSubscription;
  bool _isRunning = false;
  bool _isSyncing = false;

  /// Start the background sync service
  Future<void> start() async {
    if (_isRunning) return;

    _isRunning = true;
    
    // Start network listener
    _startNetworkListener();
    
    // Start periodic sync (every 30 seconds)
    _startPeriodicSync();
    
    // Start cleanup timer (every 6 hours)
    _startCleanupTimer();
    
    // Initial sync attempt
    await _queue.syncIfNeeded();
    
    debugPrint('BackgroundSyncService started');
  }

  /// Stop the background sync service
  Future<void> stop() async {
    if (!_isRunning) return;

    _isRunning = false;
    
    await _networkSubscription?.cancel();
    _networkSubscription = null;
    
    _periodicSyncTimer?.cancel();
    _periodicSyncTimer = null;
    
    _cleanupTimer?.cancel();
    _cleanupTimer = null;
    
    debugPrint('BackgroundSyncService stopped');
  }

  void _startNetworkListener() {
    _networkSubscription = Connectivity().onConnectivityChanged.listen((result) {
      if (!result.contains(ConnectivityResult.none)) {
        // Network is available, trigger sync
        debugPrint('Network available, triggering sync');
        _scheduleSync();
      } else {
        debugPrint('Network unavailable');
        _updateNetworkStatus('offline');
      }
    });
  }

  void _startPeriodicSync() {
    _periodicSyncTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (_isRunning && !_isSyncing) {
        _scheduleSync();
      }
    });
  }

  void _startCleanupTimer() {
    _cleanupTimer = Timer.periodic(const Duration(hours: 6), (_) {
      if (_isRunning) {
        _performCleanup();
      }
    });
  }

  void _scheduleSync() {
    // Run sync in a microtask to avoid blocking current execution
    Future.microtask(() async {
      if (!_isSyncing) {
        await _performSync();
      }
    });
  }

  Future<void> _performSync() async {
    if (_isSyncing) return;
    
    _isSyncing = true;
    _updateNetworkStatus('syncing');
    
    try {
      debugPrint('Starting background sync');
      await _queue.syncIfNeeded();
      _updateNetworkStatus('online');
      debugPrint('Background sync completed');
    } catch (e) {
      debugPrint('Background sync error: $e');
      _updateNetworkStatus('error');
    } finally {
      _isSyncing = false;
    }
  }

  Future<void> _performCleanup() async {
    try {
      debugPrint('Starting cleanup');
      await _queue.cleanupOldItems();
      debugPrint('Cleanup completed');
    } catch (e) {
      debugPrint('Cleanup error: $e');
    }
  }

  Future<void> _updateNetworkStatus(String status) async {
    try {
      await _db.updateSyncStatus({
        'network_status': status,
        'last_sync_at': DateTime.now().toIso8601String(),
      });
    } catch (e) {
      debugPrint('Failed to update network status: $e');
    }
  }

  /// Manual sync trigger
  Future<void> syncNow() async {
    await _performSync();
  }

  /// Get current sync status
  Future<Map<String, dynamic>?> getSyncStatus() async {
    final status = await _db.getSyncStatus();
    return {
      ...?status,
      'is_syncing': _isSyncing,
      'is_running': _isRunning,
    };
  }

  /// Get queue statistics
  Future<Map<String, int>> getQueueStats() async {
    return await _queue.getQueueStats();
  }

  /// Retry all failed reports
  Future<void> retryAllFailed() async {
    await _queue.retryAllFailed();
  }

  /// Check if service is running
  bool get isRunning => _isRunning;

  /// Check if currently syncing
  bool get isSyncing => _isSyncing;
}

/// Global instance for easy access
final backgroundSync = BackgroundSyncService();

/// Mixin for widgets that need sync status
mixin SyncStatusMixin {
  Future<Map<String, dynamic>?> getSyncStatus() async {
    return await backgroundSync.getSyncStatus();
  }

  Future<Map<String, int>> getQueueStats() async {
    return await backgroundSync.getQueueStats();
  }

  bool get isSyncing => backgroundSync.isSyncing;
  bool get isServiceRunning => backgroundSync.isRunning;
}
