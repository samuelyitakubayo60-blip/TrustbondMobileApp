import 'dart:io';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import 'package:path_provider/path_provider.dart';
import 'offline_database_schema.dart';

class OfflineDatabaseService {
  static final OfflineDatabaseService _instance = OfflineDatabaseService._internal();
  factory OfflineDatabaseService() => _instance;
  OfflineDatabaseService._internal();

  Database? _database;
  static const String _databaseName = 'trustbond_offline.db';
  static const int _databaseVersion = 1;

  Future<Database> get database async {
    _database ??= await _initDatabase();
    return _database!;
  }

  Future<Database> _initDatabase() async {
    String path;
    
    // For development, use project folder on desktop
    if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
      // Use current directory (should be TrustBond folder) for desktop development
      final currentDir = Directory.current.path;
      path = join(currentDir, _databaseName);
      print('Database path (desktop): $path');
    } else {
      // Use standard documents directory for mobile
      final documentsDirectory = await getApplicationDocumentsDirectory();
      path = join(documentsDirectory.path, _databaseName);
      print('Database path (mobile): $path');
    }
    
    return await openDatabase(
      path,
      version: _databaseVersion,
      onCreate: _onCreate,
      onUpgrade: _onUpgrade,
    );
  }

  Future<void> _onCreate(Database db, int version) async {
    await OfflineDatabaseSchema.initializeDatabase(db);
  }

  Future<void> _onUpgrade(Database db, int oldVersion, int newVersion) async {
    // Handle database upgrades in future versions
    if (oldVersion < newVersion) {
      // Add migration logic here when needed
    }
  }

  // Reports Queue Operations
  Future<String> insertReport(Map<String, dynamic> reportData) async {
    final db = await database;
    final queueId = reportData['queue_id'] as String;
    
    await db.insert(
      'reports_queue',
      reportData,
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
    
    return queueId;
  }

  Future<List<Map<String, dynamic>>> getPendingReports({int? limit}) async {
    final db = await database;
    
    String query = '''
      SELECT * FROM reports_queue 
      WHERE sync_status IN ('queued', 'failed')
      ORDER BY sync_priority DESC, created_at ASC
    ''';
    
    if (limit != null) {
      query += ' LIMIT $limit';
    }
    
    return await db.rawQuery(query);
  }

  Future<Map<String, dynamic>?> getReportByQueueId(String queueId) async {
    final db = await database;
    
    final results = await db.query(
      'reports_queue',
      where: 'queue_id = ?',
      whereArgs: [queueId],
    );
    
    return results.isNotEmpty ? results.first : null;
  }

  Future<void> updateReportStatus(String queueId, String status, {String? error}) async {
    final db = await database;
    
    final updateData = {
      'sync_status': status,
      'updated_at': DateTime.now().toIso8601String(),
    };
    
    if (error != null) {
      updateData['error_message'] = error;
    }
    
    await db.update(
      'reports_queue',
      updateData,
      where: 'queue_id = ?',
      whereArgs: [queueId],
    );
  }

  Future<void> updateReportWithServerData(String queueId, Map<String, dynamic> serverData) async {
    final db = await database;
    
    final updateData = {
      'updated_at': DateTime.now().toIso8601String(),
      ...serverData,
    };
    
    await db.update(
      'reports_queue',
      updateData,
      where: 'queue_id = ?',
      whereArgs: [queueId],
    );
  }

  Future<void> deleteReport(String queueId) async {
    final db = await database;
    
    await db.delete(
      'reports_queue',
      where: 'queue_id = ?',
      whereArgs: [queueId],
    );
  }

  // Evidence Queue Operations
  Future<String> insertEvidence(Map<String, dynamic> evidenceData) async {
    final db = await database;
    final evidenceId = evidenceData['evidence_id'] as String;
    
    await db.insert(
      'evidence_queue',
      evidenceData,
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
    
    return evidenceId;
  }

  Future<List<Map<String, dynamic>>> getPendingEvidence(String queueId) async {
    final db = await database;
    
    return await db.query(
      'evidence_queue',
      where: 'queue_id = ? AND status IN (?, ?)',
      whereArgs: [queueId, 'pending', 'failed'],
      orderBy: 'created_at ASC',
    );
  }

  Future<void> updateEvidenceStatus(String evidenceId, String status, {String? error}) async {
    final db = await database;
    
    final updateData = {
      'status': status,
      'updated_at': DateTime.now().toIso8601String(),
    };
    
    if (error != null) {
      updateData['error_message'] = error;
    }
    
    await db.update(
      'evidence_queue',
      updateData,
      where: 'evidence_id = ?',
      whereArgs: [evidenceId],
    );
  }

  Future<void> updateEvidenceWithServerData(String evidenceId, Map<String, dynamic> serverData) async {
    final db = await database;
    
    final updateData = {
      'updated_at': DateTime.now().toIso8601String(),
      ...serverData,
    };
    
    await db.update(
      'evidence_queue',
      updateData,
      where: 'evidence_id = ?',
      whereArgs: [evidenceId],
    );
  }

  // Device Cache Operations
  Future<void> cacheDeviceData(String deviceHash, Map<String, dynamic> deviceData) async {
    final db = await database;
    
    final cacheData = {
      'device_hash': deviceHash,
      'created_at': DateTime.now().toIso8601String(), // Ensure created_at is present
      'updated_at': DateTime.now().toIso8601String(),
      'is_registered': 1,
      ...deviceData,
    };
    
    await db.insert(
      'device_cache',
      cacheData,
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<Map<String, dynamic>?> getCachedDevice(String deviceHash) async {
    final db = await database;
    
    final results = await db.query(
      'device_cache',
      where: 'device_hash = ?',
      whereArgs: [deviceHash],
    );
    
    return results.isNotEmpty ? results.first : null;
  }

  // Incident Types Cache Operations
  Future<void> cacheIncidentTypes(List<Map<String, dynamic>> incidentTypes) async {
    final db = await database;
    final batch = db.batch();
    
    // Clear existing cache
    batch.delete('incident_types_cache');
    
    // Insert new data with expiration (24 hours)
    final expiresAt = DateTime.now().add(const Duration(hours: 24)).toIso8601String();
    final now = DateTime.now().toIso8601String();
    
    for (final incident in incidentTypes) {
      batch.insert('incident_types_cache', {
        ...incident,
        'cached_at': now,
        'expires_at': expiresAt,
      });
    }
    
    await batch.commit(noResult: true);
  }

  Future<List<Map<String, dynamic>>> getCachedIncidentTypes() async {
    final db = await database;
    final now = DateTime.now().toIso8601String();
    
    return await db.query(
      'incident_types_cache',
      where: 'expires_at > ?',
      whereArgs: [now],
      orderBy: 'incident_type_id',
    );
  }

  // Sync Status Operations
  Future<void> updateSyncStatus(Map<String, dynamic> statusData) async {
    final db = await database;
    
    final updateData = {
      'updated_at': DateTime.now().toIso8601String(),
      ...statusData,
    };
    
    await db.update(
      'sync_status',
      updateData,
      where: 'id = ?',
      whereArgs: [1],
    );
  }

  Future<Map<String, dynamic>?> getSyncStatus() async {
    final db = await database;
    
    final results = await db.query(
      'sync_status',
      where: 'id = ?',
      whereArgs: [1],
    );
    
    return results.isNotEmpty ? results.first : null;
  }

  // Statistics
  Future<Map<String, int>> getQueueStats() async {
    final db = await database;
    
    final reportsStats = await db.rawQuery('''
      SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN sync_status = 'queued' THEN 1 ELSE 0 END) as queued,
        SUM(CASE WHEN sync_status = 'syncing' THEN 1 ELSE 0 END) as syncing,
        SUM(CASE WHEN sync_status = 'completed' THEN 1 ELSE 0 END) as completed,
        SUM(CASE WHEN sync_status = 'failed' THEN 1 ELSE 0 END) as failed
      FROM reports_queue
    ''');

    final evidenceStats = await db.rawQuery('''
      SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
        SUM(CASE WHEN status = 'uploading' THEN 1 ELSE 0 END) as uploading,
        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
      FROM evidence_queue
    ''');

    return {
      'total_reports': (reportsStats.first['total'] as int?) ?? 0,
      'queued_reports': (reportsStats.first['queued'] as int?) ?? 0,
      'syncing_reports': (reportsStats.first['syncing'] as int?) ?? 0,
      'completed_reports': (reportsStats.first['completed'] as int?) ?? 0,
      'failed_reports': (reportsStats.first['failed'] as int?) ?? 0,
      'total_evidence': (evidenceStats.first['total'] as int?) ?? 0,
      'pending_evidence': (evidenceStats.first['pending'] as int?) ?? 0,
      'uploading_evidence': (evidenceStats.first['uploading'] as int?) ?? 0,
      'completed_evidence': (evidenceStats.first['completed'] as int?) ?? 0,
      'failed_evidence': (evidenceStats.first['failed'] as int?) ?? 0,
    };
  }

  // ========== HOTSPOT CACHE METHODS ==========

  /// Cache hotspot data from API
  Future<void> cacheHotspots(List<Map<String, dynamic>> hotspots) async {
    final db = await database;
    final now = DateTime.now().toIso8601String();
    final expiresAt = DateTime.now().add(const Duration(hours: 1)).toIso8601String();

    final batch = db.batch();
    
    // Clear existing hotspots
    batch.delete('hotspot_cache');
    batch.delete('hotspot_incidents');
    
    // Insert new hotspots
    for (final hotspot in hotspots) {
      final hotspotData = {
        'hotspot_id': hotspot['hotspot_id'].toString(),
        'center_lat': double.parse(hotspot['center_lat'].toString()),
        'center_long': double.parse(hotspot['center_long'].toString()),
        'risk_level': hotspot['risk_level'] as String,
        'incident_count': (hotspot['incident_count'] as int?) ?? 0,
        'time_window_hours': hotspot['time_window_hours'] as int? ?? 24,
        'radius_meters': double.parse(hotspot['radius_meters'].toString()),
        'incident_type_name': hotspot['incident_type_name'] as String?,
        'detected_at': hotspot['detected_at'] as String,
        'cached_at': now,
        'expires_at': expiresAt,
        'sector_id': hotspot['sector_id'] as int?,
        'cell_id': hotspot['cell_id'] as int?,
        'village_id': hotspot['village_id'] as int?,
      };
      
      batch.insert('hotspot_cache', hotspotData);
    }
    
    await batch.commit(noResult: true);
    print('Cached ${hotspots.length} hotspots in offline database');
  }

  /// Get cached hotspots
  Future<List<Map<String, dynamic>>> getCachedHotspots({int? sectorId, int? cellId, int? villageId}) async {
    final db = await database;
    final now = DateTime.now().toIso8601String();
    
    String whereClause = 'expires_at > ?';
    List<dynamic> whereArgs = [now];
    
    if (sectorId != null) {
      whereClause += ' AND sector_id = ?';
      whereArgs.add(sectorId);
    }
    if (cellId != null) {
      whereClause += ' AND cell_id = ?';
      whereArgs.add(cellId);
    }
    if (villageId != null) {
      whereClause += ' AND village_id = ?';
      whereArgs.add(villageId);
    }
    
    final hotspots = await db.query(
      'hotspot_cache',
      where: whereClause,
      whereArgs: whereArgs,
      orderBy: 'risk_level DESC, incident_count DESC',
    );
    
    return hotspots;
  }

  /// Get hotspot by ID
  Future<Map<String, dynamic>?> getHotspotById(String hotspotId) async {
    final db = await database;
    final now = DateTime.now().toIso8601String();
    
    final hotspots = await db.query(
      'hotspot_cache',
      where: 'hotspot_id = ? AND expires_at > ?',
      whereArgs: [hotspotId, now],
    );
    
    return hotspots.isNotEmpty ? hotspots.first : null;
  }

  /// Add incident to hotspot
  Future<void> addHotspotIncident(Map<String, dynamic> incident) async {
    final db = await database;
    
    await db.insert('hotspot_incidents', {
      'incident_id': incident['incident_id'].toString(),
      'hotspot_id': incident['hotspot_id'].toString(),
      'report_id': incident['report_id'].toString(),
      'incident_type_id': incident['incident_type_id'] as int?,
      'latitude': double.parse(incident['latitude'].toString()),
      'longitude': double.parse(incident['longitude'].toString()),
      'reported_at': incident['reported_at'] as String,
      'risk_contribution': incident['risk_contribution'] as double? ?? 1.0,
    });
  }

  /// Get incidents for a hotspot
  Future<List<Map<String, dynamic>>> getHotspotIncidents(String hotspotId) async {
    final db = await database;
    
    final incidents = await db.query(
      'hotspot_incidents',
      where: 'hotspot_id = ?',
      whereArgs: [hotspotId],
      orderBy: 'reported_at DESC',
    );
    
    return incidents;
  }

  /// Clean up expired hotspots
  Future<void> cleanupExpiredHotspots() async {
    final db = await database;
    final now = DateTime.now().toIso8601String();
    
    await db.delete(
      'hotspot_cache',
      where: 'expires_at <= ?',
      whereArgs: [now],
    );
    
    await db.delete(
      'hotspot_incidents',
      where: 'hotspot_id NOT IN (SELECT hotspot_id FROM hotspot_cache)',
    );
    
    print('Cleaned up expired hotspots');
  }

  // Cleanup Operations
  Future<void> cleanupOldCompletedItems({int daysOld = 7}) async {
    final db = await database;
    final cutoffDate = DateTime.now().subtract(Duration(days: daysOld)).toIso8601String();
    
    await db.delete(
      'reports_queue',
      where: 'status = ? AND updated_at < ?',
      whereArgs: ['completed', cutoffDate],
    );
    
    await db.delete(
      'evidence_queue',
      where: 'status = ? AND updated_at < ?',
      whereArgs: ['completed', cutoffDate],
    );
  }

  Future<void> closeDatabase() async {
    if (_database != null) {
      await _database!.close();
      _database = null;
    }
  }
}
