/// SQLite schema for offline reporting queue
/// Critical data stored locally when offline, synced when online

import 'package:sqflite/sqflite.dart';

class OfflineDatabaseSchema {
  
  /// Main offline reports queue - COMPLETE PostgreSQL reports table
  static const String createReportsQueueTable = '''
    CREATE TABLE IF NOT EXISTS reports_queue (
      queue_id TEXT PRIMARY KEY,
      sync_status TEXT DEFAULT 'queued' CHECK (sync_status IN ('queued', 'syncing', 'completed', 'failed')),
      attempts INTEGER DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      next_attempt_at TEXT,
      error_message TEXT,
      
      -- Complete PostgreSQL reports table columns
      report_id TEXT, -- Filled after server sync (UUID)
      report_number TEXT,
      device_id TEXT, -- Filled after device registration (UUID)
      device_hash TEXT NOT NULL, -- Local identifier
      incident_type_id INTEGER,
      description TEXT,
      latitude REAL NOT NULL,
      longitude REAL NOT NULL,
      gps_accuracy REAL,
      movement_speed REAL,
      was_stationary INTEGER DEFAULT 0, -- Boolean as integer
      location_id INTEGER,
      handling_station_id INTEGER,
      reported_at TEXT NOT NULL,
      status TEXT DEFAULT 'pending', -- PostgreSQL report status
      is_flagged INTEGER DEFAULT 0, -- Boolean as integer
      flag_reason TEXT,
      verification_status TEXT DEFAULT 'pending',
      verified_by INTEGER,
      verified_at TEXT,
      
      -- AI Processing Fields (CRITICAL)
      feature_vector TEXT, -- jsonb as JSON string
      ai_ready INTEGER DEFAULT 0, -- Boolean as integer
      features_extracted_at TEXT,
      features_extracted TEXT, -- timestamp with time zone as string
      
      -- Rule-Based Processing Fields (CRITICAL)
      rule_status TEXT DEFAULT 'pending',
      priority TEXT DEFAULT 'medium' NOT NULL,
      
      -- Device and Context Fields
      app_version TEXT,
      network_type TEXT,
      battery_level REAL,
      motion_level TEXT,
      village_location_id INTEGER,
      context_tags TEXT, -- text[] as JSON string
      
      -- Sync tracking
      server_report_id TEXT, -- UUID from server after sync
      sync_priority INTEGER DEFAULT 1 CHECK (sync_priority BETWEEN 1 AND 3)
    );
  ''';

  /// Evidence files queue - COMPLETE PostgreSQL evidence_files table
  static const String createEvidenceQueueTable = '''
    CREATE TABLE IF NOT EXISTS evidence_queue (
      evidence_id TEXT PRIMARY KEY,
      queue_id TEXT NOT NULL,
      status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'uploading', 'completed', 'failed')),
      attempts INTEGER DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      next_attempt_at TEXT,
      error_message TEXT,
      
      -- Complete PostgreSQL evidence_files table columns
      report_id TEXT, -- Filled after server sync (UUID)
      file_url TEXT, -- Server URL, filled after upload
      file_type TEXT CHECK (file_type IN ('photo', 'video')),
      file_size INTEGER,
      duration INTEGER,
      media_latitude REAL,
      media_longitude REAL,
      captured_at TEXT,
      uploaded_at TEXT, -- Server timestamp, filled after upload
      is_live_capture INTEGER DEFAULT 0, -- Boolean as integer
      cloudinary_public_id TEXT,
      cloudinary_url TEXT,
      
      -- AI Processing Fields (CRITICAL)
      perceptual_hash TEXT,
      blur_score REAL,
      tamper_score REAL,
      quality_label TEXT DEFAULT 'fair',
      ai_checked_at TEXT,
      
      -- Local file data
      local_file_path TEXT NOT NULL,
      
      -- Server data (filled after upload)
      server_evidence_id TEXT, -- UUID from server
      
      -- Foreign key relationship
      FOREIGN KEY (queue_id) REFERENCES reports_queue(queue_id) ON DELETE CASCADE
    );
  ''';

  /// Device registration cache - COMPLETE PostgreSQL devices table
  static const String createDeviceCacheTable = '''
    CREATE TABLE IF NOT EXISTS device_cache (
      device_hash TEXT PRIMARY KEY,
      
      -- Complete PostgreSQL devices table columns
      device_id TEXT, -- UUID from server
      first_seen_at TEXT,
      last_seen_at TEXT,
      total_reports INTEGER DEFAULT 0,
      trusted_reports INTEGER DEFAULT 0,
      flagged_reports INTEGER DEFAULT 0,
      spam_flags INTEGER DEFAULT 0,
      device_trust_score REAL DEFAULT 50.00,
      is_blacklisted INTEGER DEFAULT 0, -- Boolean as integer
      blacklist_reason TEXT,
      metadata TEXT, -- JSON as text - CRITICAL for device analytics
      is_banned INTEGER DEFAULT 0, -- Boolean as integer
      mobile_token TEXT,
      sector_location_id INTEGER, -- CRITICAL for location-based rules
      
      -- Local cache management
      is_registered INTEGER DEFAULT 0, -- Boolean as integer
      registration_data TEXT, -- JSON response from server
      last_sync_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
  ''';

  /// Incident types cache for offline reference
  static const String createIncidentTypesCacheTable = '''
    CREATE TABLE IF NOT EXISTS incident_types_cache (
      incident_type_id INTEGER PRIMARY KEY,
      type_name TEXT NOT NULL,
      description TEXT,
      severity_weight REAL DEFAULT 1.0,
      color_code TEXT,
      is_active INTEGER DEFAULT 1, -- Boolean as integer
      cached_at TEXT NOT NULL,
      expires_at TEXT NOT NULL
    );
  ''';

  /// Hotspot data cache - Complete backend hotspot data
  static const String createHotspotCacheTable = '''
    CREATE TABLE IF NOT EXISTS hotspot_cache (
      hotspot_id TEXT PRIMARY KEY,
      hotspot_name TEXT,
      center_lat REAL NOT NULL,
      center_long REAL NOT NULL,
      radius_meters REAL,
      incident_count INTEGER DEFAULT 0,
      report_ids TEXT, -- uuid[] as JSON string
      risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
      incident_type_distribution TEXT, -- jsonb as JSON string
      time_window_hours INTEGER,
      incident_type_id INTEGER,
      incident_type_name TEXT,
      detected_at TEXT NOT NULL,
      expires_at TEXT,
      is_active INTEGER DEFAULT 1, -- Boolean as integer
      
      -- Cache management
      cached_at TEXT NOT NULL,
      
      -- Location filtering
      sector_id INTEGER,
      cell_id INTEGER,
      village_id INTEGER
    );
  ''';

  /// Hotspot incidents breakdown - Individual incidents that make up hotspots
  static const String createHotspotIncidentsTable = '''
    CREATE TABLE IF NOT EXISTS hotspot_incidents (
      incident_id TEXT PRIMARY KEY,
      hotspot_id TEXT NOT NULL,
      report_id TEXT NOT NULL,
      incident_type_id INTEGER,
      latitude REAL NOT NULL,
      longitude REAL NOT NULL,
      reported_at TEXT NOT NULL,
      risk_contribution REAL DEFAULT 1.0,
      
      -- Foreign key relationship
      FOREIGN KEY (hotspot_id) REFERENCES hotspot_cache(hotspot_id) ON DELETE CASCADE
    );
  ''';

  /// Sync status and statistics
  static const String createSyncStatusTable = '''
    CREATE TABLE IF NOT EXISTS sync_status (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      last_sync_at TEXT,
      last_successful_sync_at TEXT,
      pending_reports INTEGER DEFAULT 0,
      failed_reports INTEGER DEFAULT 0,
      pending_evidence INTEGER DEFAULT 0,
      failed_evidence INTEGER DEFAULT 0,
      total_synced_reports INTEGER DEFAULT 0,
      total_synced_evidence INTEGER DEFAULT 0,
      sync_enabled INTEGER DEFAULT 1, -- Boolean as integer
      network_status TEXT DEFAULT 'unknown',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
  ''';

  /// Create all tables
  static const List<String> allTables = [
    createReportsQueueTable,
    createEvidenceQueueTable,
    createDeviceCacheTable,
    createIncidentTypesCacheTable,
    createHotspotCacheTable,
    createHotspotIncidentsTable,
    createSyncStatusTable,
  ];

  /// Indexes for performance
  static const List<String> indexes = [
    'CREATE INDEX IF NOT EXISTS idx_reports_queue_status ON reports_queue(status);',
    'CREATE INDEX IF NOT EXISTS idx_reports_queue_created_at ON reports_queue(created_at);',
    'CREATE INDEX IF NOT EXISTS idx_reports_queue_sync_priority ON reports_queue(sync_priority DESC, created_at ASC);',
    'CREATE INDEX IF NOT EXISTS idx_evidence_queue_queue_id ON evidence_queue(queue_id);',
    'CREATE INDEX IF NOT EXISTS idx_evidence_queue_status ON evidence_queue(status);',
    'CREATE INDEX IF NOT EXISTS idx_device_cache_hash ON device_cache(device_hash);',
    'CREATE INDEX IF NOT EXISTS idx_incident_types_cache_expires ON incident_types_cache(expires_at);',
    'CREATE INDEX IF NOT EXISTS idx_hotspot_cache_risk_level ON hotspot_cache(risk_level);',
    'CREATE INDEX IF NOT EXISTS idx_hotspot_cache_expires ON hotspot_cache(expires_at);',
    'CREATE INDEX IF NOT EXISTS idx_hotspot_cache_location ON hotspot_cache(sector_id, cell_id, village_id);',
    'CREATE INDEX IF NOT EXISTS idx_hotspot_incidents_hotspot_id ON hotspot_incidents(hotspot_id);',
    'CREATE INDEX IF NOT EXISTS idx_hotspot_incidents_reported_at ON hotspot_incidents(reported_at);',
  ];

  /// Initialize database with all tables and indexes
  static Future<void> initializeDatabase(Database db) async {
    for (final table in allTables) {
      await db.execute(table);
    }
    for (final index in indexes) {
      await db.execute(index);
    }
    
    // Initialize sync status
    await db.insert(
      'sync_status',
      {
        'id': 1,
        'last_sync_at': DateTime.now().toIso8601String(),
        'created_at': DateTime.now().toIso8601String(),
        'updated_at': DateTime.now().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.ignore,
    );
  }
}
