import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:geolocator/geolocator.dart';

import 'hotspot_service.dart';
import 'platform_service.dart';

/// Continuously tracks the user's GPS position and fires a local
/// notification when they enter (or remain in) a high-risk hotspot area.
///
/// - Starts a position stream (Geolocator) when [start] is called.
/// - Falls back to a periodic 3-minute poll if streaming fails.
/// - Deduplicates alerts: the same hotspot does not fire again for 15 min.
class ProximityAlertService {
  static final ProximityAlertService _instance =
      ProximityAlertService._internal();
  factory ProximityAlertService() => _instance;
  ProximityAlertService._internal();

  final _hotspotService = HotspotService();
  final _localNotifications = FlutterLocalNotificationsPlugin();

  StreamSubscription<Position>? _positionSub;
  Timer? _pollTimer;
  bool _started = false;

  // Hotspot IDs we have already alerted about, with expiry time
  final Map<String, DateTime> _alerted = {};
  static const _alertCooldown = Duration(minutes: 15);

  // Radius (metres) within which a hotspot triggers a notification
  double _radiusMeters = 1500;
  double get radiusMeters => _radiusMeters;
  set radiusMeters(double v) => _radiusMeters = v.clamp(200, 10000);

  // ── lifecycle ─────────────────────────────────────────────────────────────

  Future<void> start() async {
    if (_started) return;
    if (!PlatformService.supportsFirebase) return; // skip on desktop/web
    _started = true;

    await _initLocalNotifications();
    _startPositionStream();
    // Fallback periodic poll every 3 minutes in case stream fails
    _pollTimer = Timer.periodic(const Duration(minutes: 3), (_) => _poll());
    debugPrint('[ProximityAlert] started');
  }

  void stop() {
    _positionSub?.cancel();
    _pollTimer?.cancel();
    _started = false;
    debugPrint('[ProximityAlert] stopped');
  }

  // ── internal ─────────────────────────────────────────────────────────────

  Future<void> _initLocalNotifications() async {
    const androidSettings =
        AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosSettings = DarwinInitializationSettings();
    await _localNotifications.initialize(
      const InitializationSettings(
          android: androidSettings, iOS: iosSettings),
    );
  }

  void _startPositionStream() {
    try {
      _positionSub = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.medium,
          distanceFilter: 100, // only fire when moved 100 m
        ),
      ).listen(
        (pos) => _checkHotspots(pos.latitude, pos.longitude),
        onError: (e) {
          debugPrint('[ProximityAlert] position stream error: $e');
        },
        cancelOnError: false,
      );
    } catch (e) {
      debugPrint('[ProximityAlert] could not start stream: $e');
    }
  }

  Future<void> _poll() async {
    try {
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.medium,
          timeLimit: Duration(seconds: 15),
        ),
      );
      await _checkHotspots(pos.latitude, pos.longitude);
    } catch (_) {}
  }

  Future<void> _checkHotspots(double lat, double lng) async {
    try {
      final hotspots = await _hotspotService.getNearbyHotspots(
        lat: lat,
        lon: lng,
        radiusMeters: _radiusMeters.toInt(),
        timeWindowHours: 168, // 1 week window
      );

      final now = DateTime.now();

      // Purge expired cooldowns
      _alerted.removeWhere((_, exp) => now.isAfter(exp));

      for (final h in hotspots) {
        final risk = h.riskLevel.toLowerCase();
        if (risk != 'high' && risk != 'critical' && risk != 'active') continue;

        final dist = _haversineMeters(lat, lng, h.centerLat, h.centerLong);
        if (dist > _radiusMeters) continue;

        final key = '${h.centerLat.toStringAsFixed(4)}_${h.centerLong.toStringAsFixed(4)}';
        if (_alerted.containsKey(key)) continue; // already notified recently

        _alerted[key] = now.add(_alertCooldown);

        final distKm = (dist / 1000).toStringAsFixed(1);
        final title = risk == 'critical'
            ? '🔴 Critical security area nearby'
            : '🟠 High-risk area nearby';
        final body = h.incidentTypeName != null
            ? '${h.incidentTypeName} activity ${distKm} km from you. Stay alert.'
            : 'Security hotspot ${distKm} km from your location. Stay alert.';

        await _showNotification(title, body, key.hashCode);
        debugPrint('[ProximityAlert] fired: $title ($distKm km)');
      }
    } catch (e) {
      debugPrint('[ProximityAlert] checkHotspots error: $e');
    }
  }

  Future<void> _showNotification(String title, String body, int id) async {
    const androidDetails = AndroidNotificationDetails(
      'trustbond_proximity',
      'Nearby Safety Alerts',
      channelDescription: 'Alerts when you enter a high-risk area',
      importance: Importance.high,
      priority: Priority.high,
      showWhen: true,
    );
    const iosDetails = DarwinNotificationDetails(
      presentAlert: true,
      presentBadge: true,
      presentSound: true,
    );
    await _localNotifications.show(
      id,
      title,
      body,
      const NotificationDetails(android: androidDetails, iOS: iosDetails),
    );
  }

  static double _haversineMeters(
      double lat1, double lon1, double lat2, double lon2) {
    const r = 6371000.0;
    final dLat = (lat2 - lat1) * (math.pi / 180.0);
    final dLon = (lon2 - lon1) * (math.pi / 180.0);
    final a = math.sin(dLat / 2) * math.sin(dLat / 2) +
        math.cos(lat1 * math.pi / 180.0) *
            math.cos(lat2 * math.pi / 180.0) *
            math.sin(dLon / 2) *
            math.sin(dLon / 2);
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a));
  }
}
