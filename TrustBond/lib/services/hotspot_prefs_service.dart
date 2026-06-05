import 'dart:async';

import 'package:flutter/foundation.dart';

import 'proximity_alert_service.dart';

/// Global singleton that keeps the hotspot time-window and radius preferences
/// in sync between the Home tab and the Map tab.
///
/// Any screen that reads [timeWindowHours] or [radiusMeters] should call
/// [addListener] in initState and [removeListener] in dispose so it rebuilds
/// automatically whenever the value changes from another tab.
class HotspotPrefsService extends ChangeNotifier {
  static final HotspotPrefsService _instance = HotspotPrefsService._();
  static HotspotPrefsService get instance => _instance;
  HotspotPrefsService._();

  // ── Time window ────────────────────────────────────────────────────────────

  // Default to 1 week (168 h) — broad enough to show meaningful safety trends.
  int _timeWindowHours = 168;

  int get timeWindowHours => _timeWindowHours;

  /// Update the global time window and notify all registered listeners.
  /// Value is clamped to [1, 17520] hours (max 2 years).
  void setTimeWindow(int hours) {
    final clamped = hours.clamp(1, 17520);
    if (_timeWindowHours == clamped) return;
    _timeWindowHours = clamped;
    notifyListeners();
  }

  /// Human-readable short label for [timeWindowHours].
  static String label(int hours) {
    if (hours < 24) return '${hours}h';
    final days = hours ~/ 24;
    if (days < 7) return '${days}d';
    final weeks = days ~/ 7;
    if (days < 30) return '${weeks}w';
    final months = days ~/ 30;
    if (days < 365) return '${months}mo';
    final years = days ~/ 365;
    return '${years}yr';
  }

  // ── Radius ─────────────────────────────────────────────────────────────────

  // Default 3 km — matches ProximityAlertService default (3000 m).
  int _radiusMeters = 3000;

  int get radiusMeters => _radiusMeters;
  double get radiusKm => _radiusMeters / 1000.0;

  /// Initialise from the persisted SharedPreferences value.
  /// Call once at app startup (e.g. from MainShell._bootstrap).
  Future<void> loadSavedRadius() async {
    final m = await ProximityAlertService.loadSavedRadius();
    _radiusMeters = m.toInt();
  }

  /// Update the global radius (in metres), persist it, keep
  /// ProximityAlertService in sync, and notify all listeners.
  void setRadiusMeters(int meters) {
    final clamped = meters.clamp(100, 20000);
    if (_radiusMeters == clamped) return;
    _radiusMeters = clamped;
    unawaited(ProximityAlertService().updateRadius(clamped.toDouble()));
    notifyListeners();
  }

  /// Convenience — accepts km, converts internally.
  void setRadiusKm(double km) => setRadiusMeters((km * 1000).round());

  /// Human-readable short label for a radius in km.
  static String radiusLabel(double km) => km < 1.0
      ? '${(km * 1000).toInt()}m'
      : '${km.toStringAsFixed(km == km.toInt() ? 0 : 1)}km';
}
