import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import '../models/musanze_map_data.dart';

/// Why the GPS lookup failed.
enum LocationErrorType {
  serviceDisabled,   // GPS / Location Services turned off
  permissionDenied,  // User tapped "Deny"
  permissionDeniedForever, // User tapped "Don't ask again"
  timeout,           // GPS fix took too long
  unknown,           // Unexpected exception
}

/// Combines GPS positioning with village-level reverse geocoding
/// using the bundled Musanze GeoJSON boundaries.
class LocationService {
  static final LocationService _instance = LocationService._internal();
  factory LocationService() => _instance;
  LocationService._internal();

  MusanzeMapData? _mapData;

  // ── configuration ──────────────────────────────────────
  static const int _maxRetries = 1;
  static const Duration _gpsFastTimeout = Duration(seconds: 4);
  static const Duration _gpsSlowTimeout = Duration(seconds: 8);
  // ───────────────────────────────────────────────────────

  /// Loads the GeoJSON data (cached after first load).
  Future<MusanzeMapData> _ensureMapData() async {
    _mapData ??= await MusanzeMapData.load();
    return _mapData!;
  }

  // ── Permission / service helpers ───────────────────────

  /// Check whether Location Services are enabled on the device.
  Future<bool> isServiceEnabled() => Geolocator.isLocationServiceEnabled();

  /// Open the device location-settings page (works on Android & iOS).
  Future<bool> openLocationSettings() => Geolocator.openLocationSettings();

  /// Open the app-level permission settings.
  Future<bool> openAppSettings() => Geolocator.openAppSettings();

  // ── Core GPS method ────────────────────────────────────

  /// Gets the current GPS position with retries and timeouts.
  /// Returns a [LocationResult] that always explains what happened.
  Future<LocationResult> getCurrentPosition() async {
    // 1. Check Location Services
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      return LocationResult(
        errorType: LocationErrorType.serviceDisabled,
        error: 'Location services are turned off. '
            'Please enable GPS in your device settings.',
      );
    }

    // 2. Check / request permissions
    LocationPermission perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) {
      perm = await Geolocator.requestPermission();
      if (perm == LocationPermission.denied) {
        return LocationResult(
          errorType: LocationErrorType.permissionDenied,
          error: 'Location permission was denied. '
              'TrustBond needs GPS to determine your village.',
        );
      }
    }
    if (perm == LocationPermission.deniedForever) {
      return LocationResult(
        errorType: LocationErrorType.permissionDeniedForever,
        error: 'Location permission is permanently denied. '
            'Please enable it in App Settings → Permissions.',
      );
    }

    // 2.5 Fast path: use last known position immediately when available.
    // This gives an instant location (including offline scenarios).
    final lastKnown = await Geolocator.getLastKnownPosition();
    if (lastKnown != null) {
      return LocationResult(position: lastKnown);
    }

    // 3. Try to get a GPS fix – first fast, then slower, with retries
    Position? position;
    for (int attempt = 0; attempt <= _maxRetries; attempt++) {
      final timeout = attempt == 0 ? _gpsFastTimeout : _gpsSlowTimeout;
      try {
        position = await Geolocator.getCurrentPosition(
          locationSettings: LocationSettings(
            accuracy: attempt == 0
                ? LocationAccuracy.high
                : LocationAccuracy.medium, // relax on retry
            timeLimit: timeout,
          ),
        );
        if (position.latitude != 0.0 || position.longitude != 0.0) {
          break; // success
        }
      } on TimeoutException {
        debugPrint('[LocationService] attempt ${attempt + 1} timed out');
        // continue to retry
      } on LocationServiceDisabledException {
        return LocationResult(
          errorType: LocationErrorType.serviceDisabled,
          error: 'Location services were disabled during the request.',
        );
      } catch (e) {
        debugPrint('[LocationService] attempt ${attempt + 1} error: $e');
        // continue to retry
      }
    }

    if (position == null) {
      // Fallback to last known position when a fresh GPS fix times out.
      // This avoids showing a hard failure when the device has a recent fix.
      final lastKnown = await Geolocator.getLastKnownPosition();
      if (lastKnown != null) {
        return LocationResult(position: lastKnown);
      }

      return LocationResult(
        errorType: LocationErrorType.timeout,
        error: 'Could not get a GPS fix after ${_maxRetries + 1} attempts. '
            'Try moving to an open area with clear sky.',
      );
    }

    return LocationResult(position: position);
  }

  // ── Village lookup ─────────────────────────────────────

  /// Given GPS coordinates, find the village/cell/sector location.
  /// Falls back to nearest village if not inside any polygon.
  Future<VillageLocation?> getVillageFromCoordinates(
    double latitude,
    double longitude,
  ) async {
    final mapData = await _ensureMapData();
    return mapData.findNearestVillage(latitude, longitude);
  }

  // ── Convenience ────────────────────────────────────────

  /// Get full location info: GPS position + village location.
  Future<LocationResult> getFullLocation() async {
    final result = await getCurrentPosition();
    if (!result.hasPosition) return result; // propagate error

    final village = await getVillageFromCoordinates(
      result.latitude!,
      result.longitude!,
    );

    return LocationResult(
      position: result.position,
      village: village,
    );
  }
}

/// Result of a full location lookup.
class LocationResult {
  final Position? position;
  final VillageLocation? village;
  final String? error;
  final LocationErrorType? errorType;

  LocationResult({
    this.position,
    this.village,
    this.error,
    this.errorType,
  });

  bool get hasPosition => position != null;
  bool get hasVillage => village != null;
  bool get hasError => error != null;

  /// True when the user can fix the problem from device / app settings.
  bool get canOpenSettings =>
      errorType == LocationErrorType.serviceDisabled ||
      errorType == LocationErrorType.permissionDeniedForever;

  double? get latitude => position?.latitude;
  double? get longitude => position?.longitude;
  double? get accuracy => position?.accuracy;

  /// Human-readable location string.
  String get displayLocation {
    if (hasVillage) return village!.displayName;
    if (hasPosition) {
      return '${position!.latitude.toStringAsFixed(6)}, '
          '${position!.longitude.toStringAsFixed(6)}';
    }
    return error ?? 'Location unavailable';
  }
}

