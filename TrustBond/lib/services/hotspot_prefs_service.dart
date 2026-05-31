import 'package:flutter/foundation.dart';

/// Global singleton that keeps the hotspot time-window preference in sync
/// between the Home tab and the Map tab.
///
/// Any screen that reads [timeWindowHours] should call [addListener] in
/// initState and [removeListener] in dispose so it rebuilds automatically
/// whenever the value changes from another tab.
class HotspotPrefsService extends ChangeNotifier {
  static final HotspotPrefsService _instance = HotspotPrefsService._();
  static HotspotPrefsService get instance => _instance;
  HotspotPrefsService._();

  // Default to 1 week (168 h) so the map shows hotspots built from a meaningful
  // dataset even if the last clustering run was >24 h ago.  The backend public
  // API now uses a 7-day lookback floor anyway, but a wider default here ensures
  // the request window matches what the clustering system actually produces.
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
}
