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

  MusanzeMapPreviewPainter({
    required this.mapData,
    this.padding = 8,
    this.userLatitude,
    this.userLongitude,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final bounds = mapData.bounds;
    final drawW = size.width - padding * 2;
    final drawH = size.height - padding * 2;
    final geoAspect = bounds.lngSpan / bounds.latSpan;
    final screenAspect = drawW / drawH;
    double scale, offsetX, offsetY;

    if (screenAspect > geoAspect) {
      scale = drawH / bounds.latSpan;
      offsetX = padding + (drawW - bounds.lngSpan * scale) / 2;
      offsetY = padding;
    } else {
      scale = drawW / bounds.lngSpan;
      offsetX = padding;
      offsetY = padding + (drawH - bounds.latSpan * scale) / 2;
    }

    Offset toScreen(ui.Offset geo) {
      final x = offsetX + (geo.dx - bounds.minLng) * scale;
      final y = offsetY + (bounds.maxLat - geo.dy) * scale;
      return Offset(x, y);
    }

    // Draw sector outlines only (lightweight for preview)
    for (final feature in mapData.features) {
      final baseColor = sectorColor(feature.sector);
      final fillPaint = Paint()
        ..style = PaintingStyle.fill
        ..color = baseColor.withValues(alpha: 0.1);
      final strokePaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.4
        ..color = baseColor.withValues(alpha: 0.3);

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

    // Sector labels (small)
    for (final sector in mapData.sectors) {
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
      oldDelegate.userLongitude != userLongitude;
}
