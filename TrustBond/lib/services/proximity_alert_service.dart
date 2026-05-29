import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:geolocator/geolocator.dart';

import 'hotspot_service.dart';
import 'platform_service.dart';

/// Continuously tracks the user's GPS position and fires a local notification
/// when they enter a high-risk hotspot area.
///
/// Lifecycle:
///  - [start] — called once at app launch; sets up foreground service + stream.
///  - [updateRadius] — call whenever the user changes alert distance; restarts
///    the stream and fires an immediate check at the last known position.
///  - [stop] — called when the app is fully dismissed.
///
/// The Android foreground service notification keeps this alive even when the
/// app is backgrounded (screen off, user in another app). Force-killing the
/// app from recents will stop tracking — that is an OS-level restriction.
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
  Position? _lastKnownPosition;

  // Per-hotspot cooldown map: key → next-alert-allowed time
  final Map<String, DateTime> _alerted = {};
  static const _alertCooldown = Duration(minutes: 15);

  // Alert radius in metres — updated via [updateRadius]
  double _radiusMeters = 1500;
  double get radiusMeters => _radiusMeters;

  // ── public API ────────────────────────────────────────────────────────────

  /// Initial startup. Call once from MainShell._bootstrap().
  Future<void> start() async {
    if (_started) return;
    if (!PlatformService.supportsFirebase) return;
    _started = true;

    await _initLocalNotifications();
    await _ensureLocationPermission();
    if (!_started) return; // permission was denied

    _startPositionStream();
    // Poll every 60 s so stationary users still get alerts even with
    // no GPS movement (distanceFilter would otherwise suppress updates).
    _pollTimer = Timer.periodic(const Duration(minutes: 1), (_) => _poll());
    debugPrint('[ProximityAlert] started (radius: ${_radiusMeters.toInt()} m)');
  }

  /// Call whenever the alert radius changes (from SafetyMapScreen or settings).
  /// Restarts the stream with the new value and checks the current position
  /// immediately so the user doesn't wait up to 60 s for feedback.
  Future<void> updateRadius(double meters) async {
    final clamped = meters.clamp(100, 20000).toDouble();
    if (clamped == _radiusMeters) return;
    _radiusMeters = clamped;

    if (!_started) return;

    // Restart stream (picks up new intervalDuration / settings)
    _positionSub?.cancel();
    _startPositionStream();

    // Immediate re-check at last known position
    if (_lastKnownPosition != null) {
      // Clear cooldowns when radius changes so the user sees alerts
      // for the new area right away.
      _alerted.clear();
      await _checkHotspots(
          _lastKnownPosition!.latitude, _lastKnownPosition!.longitude);
    } else {
      await _poll();
    }

    debugPrint('[ProximityAlert] radius updated to ${clamped.toInt()} m');
  }

  /// Resumes tracking after the app returns to the foreground.
  /// Fires an immediate position check so alerts are never delayed on resume.
  Future<void> resume() async {
    if (!_started) return;
    await _poll();
  }

  void stop() {
    _positionSub?.cancel();
    _pollTimer?.cancel();
    _started = false;
    debugPrint('[ProximityAlert] stopped');
  }

  // ── setup ─────────────────────────────────────────────────────────────────

  Future<void> _initLocalNotifications() async {
    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosSettings = DarwinInitializationSettings();
    await _localNotifications.initialize(
      const InitializationSettings(android: androidSettings, iOS: iosSettings),
    );
  }

  Future<void> _ensureLocationPermission() async {
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm == LocationPermission.deniedForever ||
          perm == LocationPermission.denied) {
        debugPrint('[ProximityAlert] location permission denied — tracking disabled');
        _started = false;
        return;
      }
      // Request upgrade to "Allow all the time" on Android 10+
      if (Platform.isAndroid && perm == LocationPermission.whileInUse) {
        await Geolocator.requestPermission();
      }
    } catch (e) {
      debugPrint('[ProximityAlert] permission check error: $e');
    }
  }

  // ── position stream ───────────────────────────────────────────────────────

  void _startPositionStream() {
    try {
      final LocationSettings settings;

      if (Platform.isAndroid) {
        settings = AndroidSettings(
          accuracy: LocationAccuracy.medium,
          // 50 m filter: responsive to movement without draining battery.
          // The 60-second poll timer catches the stationary case.
          distanceFilter: 50,
          intervalDuration: const Duration(seconds: 30),
          // The foreground notification keeps this service alive when the app
          // is backgrounded. Without it Android would kill the stream.
          foregroundNotificationConfig: const ForegroundNotificationConfig(
            notificationChannelName: 'TrustBond Safety Tracking',
            notificationTitle: 'Safety Monitoring Active',
            notificationText:
                'TrustBond is monitoring your area for security alerts.',
            enableWakeLock: true,
          ),
        );
      } else if (Platform.isIOS || Platform.isMacOS) {
        settings = AppleSettings(
          accuracy: LocationAccuracy.medium,
          distanceFilter: 50,
          activityType: ActivityType.fitness,
          pauseLocationUpdatesAutomatically: false,
          allowBackgroundLocationUpdates: true,
          showBackgroundLocationIndicator: true,
        );
      } else {
        settings = const LocationSettings(
          accuracy: LocationAccuracy.medium,
          distanceFilter: 50,
        );
      }

      _positionSub = Geolocator.getPositionStream(locationSettings: settings)
          .listen(
        (pos) {
          _lastKnownPosition = pos;
          _checkHotspots(pos.latitude, pos.longitude);
        },
        onError: (e) => debugPrint('[ProximityAlert] stream error: $e'),
        cancelOnError: false,
      );
    } catch (e) {
      debugPrint('[ProximityAlert] could not start stream: $e');
    }
  }

  // ── poll (stationary fallback) ────────────────────────────────────────────

  Future<void> _poll() async {
    try {
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.medium,
          timeLimit: Duration(seconds: 20),
        ),
      );
      _lastKnownPosition = pos;
      await _checkHotspots(pos.latitude, pos.longitude);
    } catch (_) {}
  }

  // ── hotspot check ─────────────────────────────────────────────────────────

  Future<void> _checkHotspots(double lat, double lng) async {
    try {
      final hotspots = await _hotspotService.getNearbyHotspots(
        lat: lat,
        lon: lng,
        radiusMeters: _radiusMeters.toInt(),
        timeWindowHours: 168,
      );

      final now = DateTime.now();
      _alerted.removeWhere((_, exp) => now.isAfter(exp));

      for (final h in hotspots) {
        final risk = h.riskLevel.toLowerCase();
        if (risk != 'high' && risk != 'critical' && risk != 'active') continue;

        final dist = _haversineMeters(lat, lng, h.centerLat, h.centerLong);
        if (dist > _radiusMeters) continue;

        final key =
            '${h.centerLat.toStringAsFixed(4)}_${h.centerLong.toStringAsFixed(4)}';
        if (_alerted.containsKey(key)) continue;

        _alerted[key] = now.add(_alertCooldown);

        final distKm = (dist / 1000).toStringAsFixed(1);
        final title = risk == 'critical'
            ? 'Critical security area nearby'
            : 'High-risk area nearby';
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

  // ── notification ─────────────────────────────────────────────────────────

  Future<void> _showNotification(String title, String body, int id) async {
    const androidDetails = AndroidNotificationDetails(
      'trustbond_proximity',
      'Nearby Safety Alerts',
      channelDescription: 'Alerts when you enter a high-risk security area',
      importance: Importance.high,
      priority: Priority.high,
      showWhen: true,
      playSound: true,
      enableVibration: true,
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

  // ── haversine ─────────────────────────────────────────────────────────────

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
