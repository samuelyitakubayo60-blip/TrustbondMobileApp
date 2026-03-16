import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../models/musanze_map_data.dart';

/// Assigns a unique color to each sector.
Color sectorColor(String sector, {double alpha = 1.0}) {
  const palette = [
    Color(0xFF00E5B4), // accent
    Color(0xFF0099FF), // accent2
    Color(0xFFFF6B35), // warn
    Color(0xFF6C63FF), // purple
    Color(0xFF00CED1), // teal
    Color(0xFFFF3B5C), // danger
    Color(0xFFFFD700), // gold
    Color(0xFF48B8D0), // cyan
    Color(0xFFF472B6), // pink
    Color(0xFF34D399), // emerald
    Color(0xFFA78BFA), // violet
    Color(0xFFFBBF24), // amber
    Color(0xFF38BDF8), // sky
    Color(0xFFF87171), // red-light
    Color(0xFF818CF8), // indigo
  ];
  final hash = sector.hashCode.abs();
  final c = palette[hash % palette.length];
  return c.withValues(alpha: alpha);
}

/// Paints Musanze district boundaries from GeoJSON data.
class MusanzeMapPainter extends CustomPainter {
  final MusanzeMapData mapData;
  final String? highlightSector;
  final bool showLabels;
  final double padding;
  final double? userLatitude;
  final double? userLongitude;

  MusanzeMapPainter({
    required this.mapData,
    this.highlightSector,
    this.showLabels = true,
    this.padding = 12,
    this.userLatitude,
    this.userLongitude,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final bounds = mapData.bounds;
    final drawW = size.width - padding * 2;
    final drawH = size.height - padding * 2;

    // Maintain aspect ratio
    final geoAspect = bounds.lngSpan / bounds.latSpan;
    final screenAspect = drawW / drawH;
    double scale, offsetX, offsetY;

    if (screenAspect > geoAspect) {
      // Screen is wider: fit height
      scale = drawH / bounds.latSpan;
      offsetX = padding + (drawW - bounds.lngSpan * scale) / 2;
      offsetY = padding;
    } else {
      // Screen is taller: fit width
      scale = drawW / bounds.lngSpan;
      offsetX = padding;
      offsetY = padding + (drawH - bounds.latSpan * scale) / 2;
    }

    Offset toScreen(ui.Offset geo) {
      final x = offsetX + (geo.dx - bounds.minLng) * scale;
      // Invert latitude (north = top of screen)
      final y = offsetY + (bounds.maxLat - geo.dy) * scale;
      return Offset(x, y);
    }

    // Draw each village polygon
    for (final feature in mapData.features) {
      final isHighlighted =
          highlightSector == null || feature.sector == highlightSector;
      final baseColor = sectorColor(feature.sector);

      final fillPaint = Paint()
        ..style = PaintingStyle.fill
        ..color = isHighlighted
            ? baseColor.withValues(alpha: 0.18)
            : baseColor.withValues(alpha: 0.05);

      final strokePaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = isHighlighted ? 0.8 : 0.3
        ..color = isHighlighted
            ? baseColor.withValues(alpha: 0.55)
            : baseColor.withValues(alpha: 0.12);

      for (final ring in feature.rings) {
        if (ring.length < 3) continue;
        final path = Path();
        final first = toScreen(ring[0]);
        path.moveTo(first.dx, first.dy);
        for (int i = 1; i < ring.length; i++) {
          final pt = toScreen(ring[i]);
          path.lineTo(pt.dx, pt.dy);
        }
        path.close();
        canvas.drawPath(path, fillPaint);
        canvas.drawPath(path, strokePaint);
      }
    }

    // Sector outer borders (thicker)
    if (highlightSector == null) {
      for (final sector in mapData.sectors) {
        final feats = mapData.bySector(sector);
        final borderPaint = Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.2
          ..color = sectorColor(sector, alpha: 0.5);

        for (final f in feats) {
          for (final ring in f.rings) {
            if (ring.length < 3) continue;
            final path = Path();
            final first = toScreen(ring[0]);
            path.moveTo(first.dx, first.dy);
            for (int i = 1; i < ring.length; i++) {
              final pt = toScreen(ring[i]);
              path.lineTo(pt.dx, pt.dy);
            }
            path.close();
            canvas.drawPath(path, borderPaint);
          }
        }
      }
    }

    // Sector labels
    if (showLabels) {
      for (final sector in mapData.sectors) {
        if (highlightSector != null && sector != highlightSector) continue;
        final centroid = mapData.sectorCentroid(sector);
        final pos = toScreen(centroid);

        final textPainter = TextPainter(
          text: TextSpan(
            text: sector,
            style: TextStyle(
              fontSize: highlightSector != null ? 11 : 8,
              fontWeight: FontWeight.w600,
              color: sectorColor(sector, alpha: 0.85),
              shadows: const [Shadow(color: AppColors.bg, blurRadius: 3)],
            ),
          ),
          textDirection: TextDirection.ltr,
        );
        textPainter.layout();
        textPainter.paint(
          canvas,
          Offset(pos.dx - textPainter.width / 2, pos.dy - textPainter.height / 2),
        );
      }
    }

    // Draw user location marker
    if (userLatitude != null && userLongitude != null) {
      final userPos = toScreen(ui.Offset(userLongitude!, userLatitude!));
      // Check if within visible bounds
      if (userPos.dx >= 0 && userPos.dx <= size.width &&
          userPos.dy >= 0 && userPos.dy <= size.height) {
        // Outer glow
        canvas.drawCircle(
          userPos,
          14,
          Paint()
            ..color = AppColors.accent.withValues(alpha: 0.15)
            ..style = PaintingStyle.fill,
        );
        // Middle ring
        canvas.drawCircle(
          userPos,
          8,
          Paint()
            ..color = AppColors.accent.withValues(alpha: 0.3)
            ..style = PaintingStyle.fill,
        );
        // Inner dot
        canvas.drawCircle(
          userPos,
          4.5,
          Paint()
            ..color = AppColors.accent
            ..style = PaintingStyle.fill,
        );
        // White border
        canvas.drawCircle(
          userPos,
          4.5,
          Paint()
            ..color = Colors.white
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.5,
        );
      }
    }
  }

  @override
  bool shouldRepaint(MusanzeMapPainter oldDelegate) =>
      oldDelegate.highlightSector != highlightSector ||
      oldDelegate.showLabels != showLabels ||
      oldDelegate.userLatitude != userLatitude ||
      oldDelegate.userLongitude != userLongitude;
}

/// Simplified painter for small preview (home screen).
class MusanzeMapPreviewPainter extends CustomPainter {
  final MusanzeMapData mapData;
  final double padding;
  final double? userLatitude;
  final double? userLongitude;
  final VillageLocation? userVillage;
  final List<Map<String, dynamic>> sectorHotspots;

  MusanzeMapPreviewPainter({
    required this.mapData,
    this.padding = 8,
    this.userLatitude,
    this.userLongitude,
    this.userVillage,
    this.sectorHotspots = const [],
  });

  @override
  void paint(Canvas canvas, Size size) {
    // Focus on user's current area when available (cell-level zoom),
    // otherwise keep full district preview.
    final focusedFeatures = userVillage == null
        ? mapData.features
        : mapData.features
            .where((f) =>
                f.sector == userVillage!.sector &&
                f.cell == userVillage!.cell)
            .toList();

    final previewFeatures = focusedFeatures.isEmpty ? mapData.features : focusedFeatures;

    double minLng = double.infinity;
    double maxLng = -double.infinity;
    double minLat = double.infinity;
    double maxLat = -double.infinity;

    for (final f in previewFeatures) {
      for (final ring in f.rings) {
        for (final pt in ring) {
          if (pt.dx < minLng) minLng = pt.dx;
          if (pt.dx > maxLng) maxLng = pt.dx;
          if (pt.dy < minLat) minLat = pt.dy;
          if (pt.dy > maxLat) maxLat = pt.dy;
        }
      }
    }

    // Fallback to full map bounds if focused data is unexpectedly empty.
    if (minLng == double.infinity || maxLng == -double.infinity ||
        minLat == double.infinity || maxLat == -double.infinity) {
      minLng = mapData.bounds.minLng;
      maxLng = mapData.bounds.maxLng;
      minLat = mapData.bounds.minLat;
      maxLat = mapData.bounds.maxLat;
    }

    // Add small padding around focused bounds.
    const pad = 0.0025;
    minLng -= pad;
    maxLng += pad;
    minLat -= pad;
    maxLat += pad;

    final lngSpan = (maxLng - minLng).abs().clamp(0.0001, double.infinity);
    final latSpan = (maxLat - minLat).abs().clamp(0.0001, double.infinity);

    final drawW = size.width - padding * 2;
    final drawH = size.height - padding * 2;
    final geoAspect = lngSpan / latSpan;
    final screenAspect = drawW / drawH;
    double scale, offsetX, offsetY;

    if (screenAspect > geoAspect) {
      scale = drawH / latSpan;
      offsetX = padding + (drawW - lngSpan * scale) / 2;
      offsetY = padding;
    } else {
      scale = drawW / lngSpan;
      offsetX = padding;
      offsetY = padding + (drawH - latSpan * scale) / 2;
    }

    Offset toScreen(ui.Offset geo) {
      final x = offsetX + (geo.dx - minLng) * scale;
      final y = offsetY + (maxLat - geo.dy) * scale;
      return Offset(x, y);
    }

    // Draw polygons for the focused region only.
    for (final feature in previewFeatures) {
      final baseColor = sectorColor(feature.sector);
      final isUserCell = userVillage != null &&
          feature.sector == userVillage!.sector &&
          feature.cell == userVillage!.cell;
      final fillPaint = Paint()
        ..style = PaintingStyle.fill
        ..color = isUserCell
            ? baseColor.withValues(alpha: 0.22)
            : baseColor.withValues(alpha: 0.10);
      final strokePaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = isUserCell ? 0.9 : 0.4
        ..color = isUserCell
            ? baseColor.withValues(alpha: 0.7)
            : baseColor.withValues(alpha: 0.3);

      for (final ring in feature.rings) {
        if (ring.length < 3) continue;
        final path = Path();
        final first = toScreen(ring[0]);
        path.moveTo(first.dx, first.dy);
        for (int i = 1; i < ring.length; i++) {
          final pt = toScreen(ring[i]);
          path.lineTo(pt.dx, pt.dy);
        }
        path.close();
        canvas.drawPath(path, fillPaint);
        canvas.drawPath(path, strokePaint);
      }
    }

    // Sector labels (small) for sectors visible in this preview scope.
    final visibleSectors = previewFeatures.map((f) => f.sector).toSet().toList()..sort();
    for (final sector in visibleSectors) {
      final centroid = mapData.sectorCentroid(sector);
      final pos = toScreen(centroid);
      final textPainter = TextPainter(
        text: TextSpan(
          text: sector,
          style: TextStyle(
            fontSize: 6,
            fontWeight: FontWeight.w600,
            color: sectorColor(sector, alpha: 0.7),
          ),
        ),
        textDirection: TextDirection.ltr,
      );
      textPainter.layout();
      textPainter.paint(
        canvas,
        Offset(pos.dx - textPainter.width / 2, pos.dy - textPainter.height / 2),
      );
    }

    // Draw sector hotspots
    for (final hotspot in sectorHotspots) {
      final latitude = hotspot['latitude'] as double?;
      final longitude = hotspot['longitude'] as double?;
      final riskLevel = hotspot['risk_level'] as String?;
      final incidentCount = hotspot['incident_count'] as int?;
      
      if (latitude == null || longitude == null) continue;
      
      final hotspotPos = toScreen(ui.Offset(longitude, latitude));
      if (hotspotPos.dx >= 0 && hotspotPos.dx <= size.width &&
          hotspotPos.dy >= 0 && hotspotPos.dy <= size.height) {
        
        // Determine color based on risk level
        Color hotspotColor;
        switch (riskLevel?.toLowerCase()) {
          case 'high':
            hotspotColor = AppColors.danger;
            break;
          case 'medium':
            hotspotColor = AppColors.warn;
            break;
          case 'low':
            hotspotColor = AppColors.ok;
            break;
          default:
            hotspotColor = AppColors.muted;
        }
        
        // Draw hotspot circle (size based on incident count)
        final radius = incidentCount != null ? (4.0 + (incidentCount / 5).clamp(0, 4)).toDouble() : 6.0;
        
        // Outer glow
        canvas.drawCircle(
          hotspotPos,
          radius + 2,
          Paint()
            ..color = hotspotColor.withValues(alpha: 0.2)
            ..style = PaintingStyle.fill,
        );
        
        // Main hotspot circle
        canvas.drawCircle(
          hotspotPos,
          radius,
          Paint()
            ..color = hotspotColor.withValues(alpha: 0.8)
            ..style = PaintingStyle.fill,
        );
        
        // Inner highlight
        canvas.drawCircle(
          hotspotPos,
          radius - 1,
          Paint()
            ..color = hotspotColor.withValues(alpha: 0.4)
            ..style = PaintingStyle.fill,
        );
      }
    }

    // Draw user location marker on preview
    if (userLatitude != null && userLongitude != null) {
      final userPos = toScreen(ui.Offset(userLongitude!, userLatitude!));
      if (userPos.dx >= 0 && userPos.dx <= size.width &&
          userPos.dy >= 0 && userPos.dy <= size.height) {
        canvas.drawCircle(
          userPos,
          8,
          Paint()
            ..color = AppColors.accent.withValues(alpha: 0.2)
            ..style = PaintingStyle.fill,
        );
        canvas.drawCircle(
          userPos,
          4,
          Paint()
            ..color = AppColors.accent
            ..style = PaintingStyle.fill,
        );
        canvas.drawCircle(
          userPos,
          4,
          Paint()
            ..color = Colors.white
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.2,
        );
      }
    }
  }

  @override
  bool shouldRepaint(MusanzeMapPreviewPainter oldDelegate) =>
      oldDelegate.userLatitude != userLatitude ||
      oldDelegate.userLongitude != userLongitude ||
      oldDelegate.userVillage?.village != userVillage?.village ||
      oldDelegate.userVillage?.cell != userVillage?.cell ||
      oldDelegate.userVillage?.sector != userVillage?.sector ||
      oldDelegate.sectorHotspots.length != sectorHotspots.length;
}
