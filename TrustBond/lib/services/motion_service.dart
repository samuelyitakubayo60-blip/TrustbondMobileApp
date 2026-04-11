import 'dart:async';
import 'dart:math' show sqrt;
import 'dart:io' show Platform;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:sensors_plus/sensors_plus.dart';

/// Result of sampling device motion (accelerometer).
class MotionSample {
  final String motionLevel; // low, medium, high
  final double? movementSpeed; // proxy from acceleration variance
  final bool wasStationary;

  MotionSample({
    required this.motionLevel,
    this.movementSpeed,
    required this.wasStationary,
  });
}

/// Samples accelerometer for [durationSeconds] and returns motion level.
/// On web, desktop, or if sensors unavailable, returns a default (low, stationary).
Future<MotionSample> collectMotionSample({double durationSeconds = 1.2}) async {
  if (kIsWeb || Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
    return MotionSample(motionLevel: 'low', movementSpeed: 0.0, wasStationary: true);
  }

  final List<double> magnitudes = [];
  StreamSubscription<AccelerometerEvent>? sub;

  try {
    sub = accelerometerEventStream().listen((AccelerometerEvent event) {
      final mag = (event.x * event.x + event.y * event.y + event.z * event.z).abs();
      magnitudes.add(mag);
    });

    await Future.delayed(Duration(milliseconds: (durationSeconds * 1000).toInt()));
  } catch (e) {
    // Sensors not available or other error, return default
    return MotionSample(motionLevel: 'low', movementSpeed: 0.0, wasStationary: true);
  } finally {
    try {
      await sub?.cancel();
    } catch (e) {
      // Ignore cancellation errors
    }
  }

  return _computeMotion(magnitudes);
}

MotionSample _computeMotion(List<double> magnitudes) {
  if (magnitudes.isEmpty) {
    return MotionSample(motionLevel: 'low', movementSpeed: 0.0, wasStationary: true);
  }

  final mean = magnitudes.reduce((a, b) => a + b) / magnitudes.length;
  final variance = magnitudes.map((m) => (m - mean) * (m - mean)).reduce((a, b) => a + b) / magnitudes.length;
  final std = variance > 0 ? sqrt(variance) : 0.0;

  const lowThreshold = 0.5;
  const highThreshold = 3.0;

  bool wasStationary = std < lowThreshold;
  String motionLevel;
  if (std < lowThreshold) {
    motionLevel = 'low';
  } else if (std < highThreshold) {
    motionLevel = 'medium';
  } else {
    motionLevel = 'high';
  }

  return MotionSample(
    motionLevel: motionLevel,
    movementSpeed: std,
    wasStationary: wasStationary,
  );
}
