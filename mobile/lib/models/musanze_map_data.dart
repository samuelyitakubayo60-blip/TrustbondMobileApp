import 'dart:convert';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/services.dart' show rootBundle;

/// Simple DTO for village/cell/sector info used in the app.
class VillageLocation {
  final String village;
  final String cell;
  final String sector;

  VillageLocation({
    required this.village,
    required this.cell,
    required this.sector,
  });

  String get displayName => '$village, $cell, $sector';
}

/// Geographic bounds for the whole Musanze dataset.
class MusanzeBounds {
  final double minLat;
  final double maxLat;
  final double minLng;
  final double maxLng;

  MusanzeBounds({
    required this.minLat,
    required this.maxLat,
    required this.minLng,
    required this.maxLng,
  });

  double get latSpan => maxLat - minLat;
  double get lngSpan => maxLng - minLng;
}

/// One polygon feature (usually a village) from the GeoJSON.
class MusanzeFeature {
  final String sector;
  final String cell;
  final String village;

  /// Rings as lists of [ui.Offset] where dx = longitude, dy = latitude.
  final List<List<ui.Offset>> rings;

  MusanzeFeature({
    required this.sector,
    required this.cell,
    required this.village,
    required this.rings,
  });
}

/// Parsed Musanze boundaries + helper methods for lookups.
class MusanzeMapData {
  final List<MusanzeFeature> features;

  MusanzeMapData({required this.features});

  /// Load GeoJSON from assets.
  ///
  /// Make sure you have copied:
  /// - backend/musanze/musanze_boundaries.geojson
  ///   to: mobile/assets/musanze_boundaries.geojson
  /// and that "assets/" is listed in pubspec.yaml.
  static Future<MusanzeMapData> load() async {
    final text =
        await rootBundle.loadString('assets/musanze_boundaries.geojson');
    final data = jsonDecode(text) as Map<String, dynamic>;

    final feats = <MusanzeFeature>[];
    final featuresJson = data['features'] as List<dynamic>? ?? const [];

    for (final f in featuresJson) {
      final mf = _parseFeature(f as Map<String, dynamic>);
      if (mf != null) {
        feats.add(mf);
      }
    }
    return MusanzeMapData(features: feats);
  }

  static MusanzeFeature? _parseFeature(Map<String, dynamic> json) {
    final props = json['properties'] as Map<String, dynamic>? ?? const {};
    final geom = json['geometry'] as Map<String, dynamic>? ?? const {};
    final type = geom['type'] as String? ?? '';
    final coords = geom['coordinates'];

    final sector = (props['sector'] ??
            props['SECTOR'] ??
            props['sector_name'] ??
            '') as String;
    final cell =
        (props['cell'] ?? props['CELL'] ?? props['cell_name'] ?? '') as String;
    final village = (props['village'] ??
            props['VILLAGE'] ??
            props['village_name'] ??
            '') as String;

    if (coords == null) return null;

    final rings = <List<ui.Offset>>[];

    List<List<dynamic>> outer;
    if (type == 'Polygon') {
      outer = (coords as List).cast<List<dynamic>>();
    } else if (type == 'MultiPolygon') {
      // Flatten all polygon rings
      outer = <List<dynamic>>[];
      for (final poly in (coords as List)) {
        for (final ring in (poly as List)) {
          outer.add(ring as List<dynamic>);
        }
      }
    } else {
      return null;
    }

    for (final ring in outer) {
      final pts = <ui.Offset>[];
      for (final coord in ring) {
        if (coord is List && coord.length >= 2) {
          final lng = (coord[0] as num).toDouble();
          final lat = (coord[1] as num).toDouble();
          pts.add(ui.Offset(lng, lat));
        }
      }
      if (pts.length >= 3) {
        rings.add(pts);
      }
    }

    if (rings.isEmpty) return null;

    return MusanzeFeature(
      sector: sector,
      cell: cell,
      village: village,
      rings: rings,
    );
  }

  /// Unique list of sector names.
  List<String> get sectors =>
      {for (final f in features) f.sector}.where((s) => s.isNotEmpty).toList();

  /// All features in a given sector.
  List<MusanzeFeature> bySector(String sector) =>
      features.where((f) => f.sector == sector).toList();

  /// All villages in a given sector.
  List<String> villagesIn(String sector) =>
      {for (final f in features.where((f) => f.sector == sector)) f.village}
          .where((v) => v.isNotEmpty)
          .toList();

  /// All cells in a given sector.
  List<String> cellsIn(String sector) =>
      {for (final f in features.where((f) => f.sector == sector)) f.cell}
          .where((c) => c.isNotEmpty)
          .toList();

  /// Overall geographic bounds.
  MusanzeBounds get bounds {
    double? minLat, maxLat, minLng, maxLng;
    for (final f in features) {
      for (final ring in f.rings) {
        for (final p in ring) {
          final lng = p.dx;
          final lat = p.dy;
          minLat = minLat == null ? lat : math.min(minLat, lat);
          maxLat = maxLat == null ? lat : math.max(maxLat, lat);
          minLng = minLng == null ? lng : math.min(minLng, lng);
          maxLng = maxLng == null ? lng : math.max(maxLng, lng);
        }
      }
    }
    return MusanzeBounds(
      minLat: minLat ?? 0,
      maxLat: maxLat ?? 0,
      minLng: minLng ?? 0,
      maxLng: maxLng ?? 0,
    );
  }

  /// Centroid of a sector (used for labeling and camera movement).
  ui.Offset sectorCentroid(String sector) {
    final feats = bySector(sector);
    if (feats.isEmpty) return const ui.Offset(29.6347, -1.4975); // Musanze
    double sumLat = 0, sumLng = 0;
    int count = 0;
    for (final f in feats) {
      for (final ring in f.rings) {
        for (final p in ring) {
          sumLat += p.dy;
          sumLng += p.dx;
          count++;
        }
      }
    }
    if (count == 0) return const ui.Offset(29.6347, -1.4975);
    return ui.Offset(sumLng / count, sumLat / count);
  }

  /// All villages in a sector (used for list at bottom of map).
  List<VillageLocation> bySectorLocations(String sector) {
    return [
      for (final f in features.where((f) => f.sector == sector))
        VillageLocation(village: f.village, cell: f.cell, sector: f.sector),
    ];
  }

  /// Find the nearest village to a given coordinate.
  Future<VillageLocation?> findNearestVillage(
      double lat, double lng) async {
    // Simple nearest-centroid search over villages
    VillageLocation? best;
    double bestDist = double.infinity;
    for (final f in features) {
      // Approximate centroid of first ring
      if (f.rings.isEmpty || f.rings.first.isEmpty) continue;
      final ring = f.rings.first;
      double sumLat = 0, sumLng = 0;
      for (final p in ring) {
        sumLat += p.dy;
        sumLng += p.dx;
      }
      final cLat = sumLat / ring.length;
      final cLng = sumLng / ring.length;
      final dLat = lat - cLat;
      final dLng = lng - cLng;
      final dist = dLat * dLat + dLng * dLng;
      if (dist < bestDist) {
        bestDist = dist;
        best = VillageLocation(
          village: f.village,
          cell: f.cell,
          sector: f.sector,
        );
      }
    }
    return best;
  }
}

