import 'dart:math';
import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../utils/date_time_utils.dart';

/// Circular trust score ring widget (matches the SVG ring in the mockup).
class TrustScoreRing extends StatelessWidget {
  final double score; // 0-100
  final double size;
  final double strokeWidth;
  final Color? color;

  const TrustScoreRing({
    super.key,
    required this.score,
    this.size = 62,
    this.strokeWidth = 5,
    this.color,
  });

  @override
  Widget build(BuildContext context) {
    final c = color ?? AppColors.accent;
    return SizedBox(
      width: size,
      height: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          CustomPaint(
            size: Size(size, size),
            painter: _RingPainter(
              progress: (score / 100).clamp(0, 1),
              color: c,
              trackColor: c.withValues(alpha: 0.1),
              strokeWidth: strokeWidth,
            ),
          ),
          Text(
            score.toInt().toString(),
            style: TextStyle(
              fontSize: size * 0.21,
              fontWeight: FontWeight.w700,
              fontFamily: 'monospace',
              color: c,
            ),
          ),
        ],
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  final double progress;
  final Color color;
  final Color trackColor;
  final double strokeWidth;

  _RingPainter({
    required this.progress,
    required this.color,
    required this.trackColor,
    required this.strokeWidth,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = (size.width - strokeWidth) / 2;

    // Track
    canvas.drawCircle(
      center,
      radius,
      Paint()
        ..color = trackColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth,
    );

    // Progress arc
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      -pi / 2, // start at top
      2 * pi * progress,
      false,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(covariant _RingPainter old) =>
      old.progress != progress || old.color != color;
}

/// Status badge (ok, warn, err, info, mute).
class StatusBadge extends StatelessWidget {
  final String label;
  final BadgeType type;

  const StatusBadge({super.key, required this.label, this.type = BadgeType.mute});

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = switch (type) {
      BadgeType.ok => (AppColors.ok.withValues(alpha: 0.13), AppColors.ok),
      BadgeType.warn => (AppColors.warn.withValues(alpha: 0.13), AppColors.warn),
      BadgeType.err => (AppColors.danger.withValues(alpha: 0.13), AppColors.danger),
      BadgeType.info => (AppColors.accent2.withValues(alpha: 0.13), AppColors.accent2),
      BadgeType.mute => (AppColors.surface2, AppColors.muted),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.4,
          color: fg,
        ),
      ),
    );
  }
}

enum BadgeType { ok, warn, err, info, mute }

enum DeliveryUiState { pending, syncing, sent, failed }

/// Converts a rule_status string to a BadgeType.
BadgeType badgeTypeFromStatus(String status) {
  return switch (status.toLowerCase()) {
    'confirmed' || 'verified' || 'trusted' => BadgeType.ok,
    'investigating' || 'under_review' || 'flagged' => BadgeType.warn,
    'rejected' || 'false_report' => BadgeType.err,
    'ai_verified' => BadgeType.info,
    _ => BadgeType.mute,
  };
}

/// Report list item card (matches ri class in mockup).
class ReportItemCard extends StatelessWidget {
  final String icon;
  final Color iconBg;
  final String typeName;
  final String description;
  final String timeLabel;
  final String statusLabel;
  final BadgeType statusType;
  final VoidCallback? onTap;
  final String? reportNumber;
  final double? trustScore;
  final DeliveryUiState? deliveryState;
  final bool showDeliveryIndicator;
  final VoidCallback? onRetryTap;
  final bool showRetryLink;

  const ReportItemCard({
    super.key,
    required this.icon,
    required this.iconBg,
    required this.typeName,
    required this.description,
    required this.timeLabel,
    required this.statusLabel,
    required this.statusType,
    this.onTap,
    this.reportNumber,
    this.trustScore,
    this.deliveryState,
    this.showDeliveryIndicator = false,
    this.onRetryTap,
    this.showRetryLink = false,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(16),
        margin: const EdgeInsets.only(bottom: 14),
        decoration: BoxDecoration(
          color: AppColors.card,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(18),
        ),
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: iconBg,
                borderRadius: BorderRadius.circular(12),
              ),
              alignment: Alignment.center,
              child: Text(icon, style: const TextStyle(fontSize: 18)),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    typeName,
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: AppColors.text,
                    ),
                  ),
                  if (reportNumber != null || trustScore != null) ...[
                    const SizedBox(height: 2),
                    Text(
                      [
                        if (reportNumber != null) reportNumber,
                        if (trustScore != null) '${(trustScore ?? 0).round()}/100',
                      ].join(' · '),
                      style: const TextStyle(
                        fontSize: 10,
                        color: AppColors.muted,
                        fontFamily: 'monospace',
                      ),
                    ),
                  ],
                  const SizedBox(height: 4),
                  Text(
                    description,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 12, color: AppColors.muted),
                  ),
                  const SizedBox(height: 7),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        timeLabel,
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.muted,
                          fontFamily: 'monospace',
                        ),
                      ),
                      StatusBadge(label: statusLabel, type: statusType),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Section header with line (matches .sec class).
class SectionHeader extends StatelessWidget {
  final String label;

  const SectionHeader(this.label, {super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 14, bottom: 9),
      child: Row(
        children: [
          Text(
            label.toUpperCase(),
            style: const TextStyle(
              fontSize: 10,
              color: AppColors.muted,
              letterSpacing: 1.5,
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(width: 8),
          const Expanded(child: Divider(color: AppColors.border)),
        ],
      ),
    );
  }
}

/// Step indicators (the dots at the top of multi-step flows).
class StepIndicators extends StatelessWidget {
  final int total;
  final int current; // 0-indexed

  const StepIndicators({super.key, required this.total, required this.current});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(total, (i) {
        final isActive = i == current;
        final isDone = i < current;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 300),
          margin: const EdgeInsets.symmetric(horizontal: 3),
          width: isActive ? 22 : 8,
          height: 8,
          decoration: BoxDecoration(
            color: isActive
                ? AppColors.accent
                : isDone
                    ? AppColors.accent.withValues(alpha: 0.45)
                    : AppColors.surface3,
            borderRadius: BorderRadius.circular(isActive ? 4 : 50),
          ),
        );
      }),
    );
  }
}

/// Gradient accent line separator.
class AccentLine extends StatelessWidget {
  const AccentLine({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 2,
      margin: const EdgeInsets.symmetric(vertical: 16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(1),
        gradient: const LinearGradient(
          colors: [Colors.transparent, AppColors.accent, Colors.transparent],
        ),
      ),
    );
  }
}

/// Stat box (matches .sbox class).
class StatBox extends StatelessWidget {
  final String value;
  final String label;
  final Color valueColor;

  const StatBox({
    super.key,
    required this.value,
    required this.label,
    this.valueColor = AppColors.ok,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: AppColors.surface2,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        children: [
          Text(
            value,
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w700,
              fontFamily: 'monospace',
              color: valueColor,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            label.toUpperCase(),
            style: const TextStyle(
              fontSize: 10,
              color: AppColors.muted,
              letterSpacing: 0.4,
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Shared helper functions (used by multiple screens) ─────────────────────

/// Returns an emoji icon for the given incident type name.
String iconForIncidentType(String typeName) {
  final l = typeName.toLowerCase();
  if (l.contains('suspicious')) return '👁️';
  if (l.contains('theft') || l.contains('robbery')) return '💼';
  if (l.contains('vandalism')) return '🏚️';
  if (l.contains('assault')) return '⚠️';
  if (l.contains('traffic')) return '🚗';
  if (l.contains('drug')) return '💊';
  if (l.contains('fire') || l.contains('hazard')) return '🔥';
  if (l.contains('noise') || l.contains('disturbance')) return '🔊';
  if (l.contains('domestic')) return '🏠';
  if (l.contains('fraud') || l.contains('scam')) return '🎭';
  if (l.contains('harassment')) return '🚫';
  return '📋';
}

/// Returns a color for the given incident type name.
Color colorForIncidentType(String typeName) {
  final l = typeName.toLowerCase();
  if (l.contains('suspicious') || l.contains('assault')) return AppColors.danger;
  if (l.contains('theft') || l.contains('drug')) return AppColors.warn;
  if (l.contains('vandalism') || l.contains('traffic')) return AppColors.accent2;
  if (l.contains('fire') || l.contains('hazard')) return AppColors.warn;
  if (l.contains('domestic')) return AppColors.danger;
  if (l.contains('fraud') || l.contains('scam')) return AppColors.warn;
  if (l.contains('harassment')) return AppColors.danger;
  return AppColors.accent;
}

/// Formats a snake_case rule status into Title Case.
String formatStatus(String status) {
  return status
      .replaceAll('_', ' ')
      .split(' ')
      .map((w) => w.isEmpty ? '' : '${w[0].toUpperCase()}${w.substring(1)}')
      .join(' ');
}

/// Returns a human-readable time-ago string.
String timeAgo(DateTime dt) {
  return formatTimeAgo(dt);
}
