import 'dart:convert';
import 'dart:math' as math;
import 'dart:ui' as ui;
import 'package:flutter/services.dart' show rootBundle;

/// Result of a reverse-geocode lookup against the Musanze GeoJSON.
class VillageLocation {
  final String village;
  final String cell;
  final String sector;

  VillageLocation({
    required this.village,
    required this.cell,
    required this.sector,
  });

  /// Human-readable display string.
  String get displayName => '$village, $cell, $sector';

  @override
  String toString() => displayName;
}

/// Bounding box for the entire dataset.
class MapBounds {
  final double minLng;
  final double maxLng;
  final double minLat;
  final double maxLat;

  MapBounds(this.minLng, this.maxLng, this.minLat, this.maxLat);

  double get lngSpan => maxLng - minLng;
  double get latSpan => maxLat - minLat;
}

/// Parsed Musanze boundary feature (one village polygon).
class MapFeature {
  final String sector;
  final String cell;
  final String village;
  final List<List<ui.Offset>> rings; // lng,lat as Offset(lng, lat)

  MapFeature({
    required this.sector,
    required this.cell,
    required this.village,
    required this.rings,
  });
}

/// Holds all parsed data for the Musanze map.
class MusanzeMapData {
  static MusanzeMapData? _cached;
  static Future<MusanzeMapData>? _loadingFuture;

  final List<MapFeature> features;
  final MapBounds bounds;
  final List<String> sectors;

  MusanzeMapData({
    required this.features,
    required this.bounds,
    required this.sectors,
  });

  /// Features filtered by sector name.
  List<MapFeature> bySector(String sector) =>
      features.where((f) => f.sector == sector).toList();

  /// All unique cell names within a sector.
  List<String> cellsIn(String sector) =>
      features.where((f) => f.sector == sector).map((f) => f.cell).toSet().toList()..sort();

  /// All unique village names within a cell.
  List<String> villagesIn(String sector, String cell) =>
      features.where((f) => f.sector == sector && f.cell == cell).map((f) => f.village).toSet().toList()..sort();

  /// Sector centroid (average of all polygon points in sector).
  ui.Offset sectorCentroid(String sector) {
    final feats = bySector(sector);
    if (feats.isEmpty) return ui.Offset.zero;
    double sumLng = 0, sumLat = 0;
    int count = 0;
    for (final f in feats) {
      for (final ring in f.rings) {
        for (final pt in ring) {
          sumLng += pt.dx;
          sumLat += pt.dy;
          count++;
        }
      }
    }
    return ui.Offset(sumLng / count, sumLat / count);
  }

  /// Find which village a GPS point (latitude, longitude) falls in.
  /// Returns null if the point is outside all village polygons.
  VillageLocation? findVillage(double latitude, double longitude) {
    final point = ui.Offset(longitude, latitude); // GeoJSON is lng,lat
    for (final feature in features) {
      for (final ring in feature.rings) {
        if (_pointInPolygon(point, ring)) {
          return VillageLocation(
            village: feature.village,
            cell: feature.cell,
            sector: feature.sector,
          );
        }
      }
    }
    return null;
  }

  /// Find the nearest village to a GPS point (fallback when point-in-polygon misses).
  VillageLocation? findNearestVillage(double latitude, double longitude) {
    // First try exact match
    final exact = findVillage(latitude, longitude);
    if (exact != null) return exact;

    // Fallback: find the closest village centroid, but only if reasonably close
    final point = ui.Offset(longitude, latitude);
    double minDist = double.infinity;
    MapFeature? closest;

    for (final feature in features) {
      for (final ring in feature.rings) {
        if (ring.isEmpty) continue;
        // Compute centroid of this ring
        double sumX = 0, sumY = 0;
        for (final pt in ring) {
          sumX += pt.dx;
          sumY += pt.dy;
        }
        final centroid = ui.Offset(sumX / ring.length, sumY / ring.length);
        final dist = _distance(point, centroid);
        if (dist < minDist) {
          minDist = dist;
          closest = feature;
        }
      }
    }

    // Only return a location if the user is within a reasonable distance of Musanze
    // Maximum distance: ~0.1 degrees (~11km) - this should cover the entire Musanze district
    const double maxDistance = 0.1;
    if (closest != null && minDist <= maxDistance) {
      return VillageLocation(
        village: closest.village,
        cell: closest.cell,
        sector: closest.sector,
      );
    }
    
    // User is outside Musanze district
    return null;
  }

  /// Ray-casting point-in-polygon algorithm.
  static bool _pointInPolygon(ui.Offset point, List<ui.Offset> polygon) {
    bool inside = false;
    final n = polygon.length;
    for (int i = 0, j = n - 1; i < n; j = i++) {
      final xi = polygon[i].dx, yi = polygon[i].dy;
      final xj = polygon[j].dx, yj = polygon[j].dy;

      if (((yi > point.dy) != (yj > point.dy)) &&
          (point.dx < (xj - xi) * (point.dy - yi) / (yj - yi) + xi)) {
        inside = !inside;
      }
    }
    return inside;
  }

  /// Euclidean distance between two points (good enough for small areas).
  static double _distance(ui.Offset a, ui.Offset b) {
    final dx = a.dx - b.dx;
    final dy = a.dy - b.dy;
    return math.sqrt(dx * dx + dy * dy);
  }

  /// Load and parse from bundled asset.
  static Future<MusanzeMapData> load() async {
    if (_cached != null) return _cached!;
    if (_loadingFuture != null) return _loadingFuture!;

    _loadingFuture = () async {
      final raw = await rootBundle.loadString('assets/musanze_boundaries.geojson');
      final parsed = parse(raw);
      _cached = parsed;
      _loadingFuture = null;
      return parsed;
    }();

    return _loadingFuture!;
  }

  /// Parse a GeoJSON string.
  static MusanzeMapData parse(String geojsonString) {
    final json = jsonDecode(geojsonString) as Map<String, dynamic>;
    final rawFeatures = json['features'] as List<dynamic>;

    double minLng = double.infinity, maxLng = -double.infinity;
    double minLat = double.infinity, maxLat = -double.infinity;
    final sectorSet = <String>{};
    final features = <MapFeature>[];

    for (final raw in rawFeatures) {
      final props = raw['properties'] as Map<String, dynamic>;
      final geom = raw['geometry'] as Map<String, dynamic>;
      // Support both asset keys (Sector/Cell/Village) and backend keys (sector/cell/village)
      final sector = (props['Sector'] ?? props['sector'] ?? props['sector_name']) as String? ?? '';
      final cell = (props['Cell'] ?? props['cell'] ?? props['cell_name']) as String? ?? '';
      final village = (props['Village'] ?? props['village'] ?? props['village_name']) as String? ?? '';
      sectorSet.add(sector);

      final geoType = geom['type'] as String? ?? 'Polygon';
      final coordsRaw = geom['coordinates'] as List<dynamic>;

      // Normalise: MultiPolygon → list of polygon coords; Polygon → wrap in list.
      final List<List<dynamic>> polygons;
      if (geoType == 'MultiPolygon') {
        polygons = coordsRaw.map((p) => p as List<dynamic>).toList();
      } else {
        polygons = [coordsRaw];
      }

      for (final polyCoords in polygons) {
        final rings = <List<ui.Offset>>[];
        for (final ringRaw in polyCoords) {
          final ring = <ui.Offset>[];
          for (final pt in ringRaw as List<dynamic>) {
            final lng = (pt[0] as num).toDouble();
            final lat = (pt[1] as num).toDouble();
            if (lng < minLng) minLng = lng;
            if (lng > maxLng) maxLng = lng;
            if (lat < minLat) minLat = lat;
            if (lat > maxLat) maxLat = lat;
            ring.add(ui.Offset(lng, lat));
          }
          rings.add(ring);
        }

        features.add(MapFeature(
          sector: sector,
          cell: cell,
          village: village,
          rings: rings,
        ));
      }
    }

    final sectors = sectorSet.toList()..sort();
    return MusanzeMapData(
      features: features,
      bounds: MapBounds(minLng, maxLng, minLat, maxLat),
      sectors: sectors,
    );
  }
}

