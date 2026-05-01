import 'package:flutter/material.dart';
import '../services/guidance_service.dart';

class GuidanceCard extends StatelessWidget {
  final GuidanceItem item;
  final VoidCallback? onTap;

  const GuidanceCard({
    Key? key,
    required this.item,
    this.onTap,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    Color cardColor;
    Color textColor;
    IconData iconData;
    
    switch (item.level) {
      case 'critical':
        cardColor = Colors.red.shade50;
        textColor = Colors.red.shade900;
        iconData = Icons.error;
        break;
      case 'warning':
        cardColor = Colors.orange.shade50;
        textColor = Colors.orange.shade900;
        iconData = Icons.warning;
        break;
      case 'info':
        cardColor = Colors.blue.shade50;
        textColor = Colors.blue.shade900;
        iconData = Icons.info;
        break;
      case 'success':
        cardColor = Colors.green.shade50;
        textColor = Colors.green.shade900;
        iconData = Icons.check_circle;
        break;
      default:
        cardColor = Colors.grey.shade50;
        textColor = Colors.grey.shade900;
        iconData = Icons.info;
    }

    return Card(
      color: cardColor,
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                iconData,
                color: textColor,
                size: 20,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.title,
                      style: TextStyle(
                        color: textColor,
                        fontWeight: FontWeight.bold,
                        fontSize: 14,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      item.message,
                      style: TextStyle(
                        color: textColor,
                        fontSize: 12,
                      ),
                    ),
                    if (item.suggestedAction != null) ...[
                      const SizedBox(height: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: textColor.withOpacity(0.1),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          '💡 ${item.suggestedAction}',
                          style: TextStyle(
                            color: textColor,
                            fontSize: 11,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (item.actionable)
                Icon(
                  Icons.chevron_right,
                  color: textColor,
                  size: 16,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class TrustScoreDisplay extends StatelessWidget {
  final TrustScoreEstimate trustEstimate;

  const TrustScoreDisplay({
    Key? key,
    required this.trustEstimate,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.all(16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Trust Score',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _getConfidenceColor().withOpacity(0.1),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    trustEstimate.confidenceLevel,
                    style: TextStyle(
                      color: _getConfidenceColor(),
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            
            // Main score display
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${trustEstimate.totalScore.toInt()}',
                        style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                          fontWeight: FontWeight.bold,
                          color: _getScoreColor(trustEstimate.totalScore),
                        ),
                      ),
                      Text(
                        '/ 100',
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: Colors.grey.shade600,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  width: 100,
                  height: 100,
                  child: Stack(
                    children: [
                      Center(
                        child: SizedBox(
                          width: 80,
                          height: 80,
                          child: CircularProgressIndicator(
                            value: trustEstimate.totalScore / 100,
                            strokeWidth: 8,
                            backgroundColor: Colors.grey.shade200,
                            valueColor: AlwaysStoppedAnimation<Color>(
                              _getScoreColor(trustEstimate.totalScore),
                            ),
                          ),
                        ),
                      ),
                      Center(
                        child: Icon(
                          trustEstimate.willBeVerified ? Icons.check : Icons.hourglass_empty,
                          color: _getScoreColor(trustEstimate.totalScore),
                          size: 24,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            
            const SizedBox(height: 16),
            
            // Verification probability
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: trustEstimate.willBeVerified 
                    ? Colors.green.shade50 
                    : Colors.orange.shade50,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(
                    trustEstimate.willBeVerified ? Icons.verified : Icons.pending,
                    color: trustEstimate.willBeVerified 
                        ? Colors.green.shade700 
                        : Colors.orange.shade700,
                    size: 20,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Verification Probability: ${trustEstimate.verificationProbability}',
                      style: TextStyle(
                        color: trustEstimate.willBeVerified 
                            ? Colors.green.shade700 
                            : Colors.orange.shade700,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            
            const SizedBox(height: 12),
            
            // Model contributions
            Text(
              'Contributing Models: ${trustEstimate.contributingModels}',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Colors.grey.shade600,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Color _getScoreColor(double score) {
    if (score >= 70) return Colors.green;
    if (score >= 45) return Colors.orange;
    return Colors.red;
  }

  Color _getConfidenceColor() {
    switch (trustEstimate.confidence) {
      case 'high_confidence':
        return Colors.green;
      case 'medium_confidence':
        return Colors.orange;
      case 'low_confidence':
        return Colors.red;
      case 'reject':
        return Colors.red.shade900;
      default:
        return Colors.grey;
    }
  }
}

class DescriptionQualityIndicator extends StatelessWidget {
  final DescriptionValidationResponse validation;

  const DescriptionQualityIndicator({
    Key? key,
    required this.validation,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          // Quality score
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      'Quality: ${validation.qualityScore.toInt()}%',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        color: _getQualityColor(validation.qualityScore),
                        fontSize: 12,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Icon(
                      validation.isValid ? Icons.check_circle : Icons.warning,
                      color: validation.isValid ? Colors.green : Colors.orange,
                      size: 16,
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                LinearProgressIndicator(
                  value: validation.qualityScore / 100,
                  backgroundColor: Colors.grey.shade200,
                  valueColor: AlwaysStoppedAnimation<Color>(
                    _getQualityColor(validation.qualityScore),
                  ),
                ),
              ],
            ),
          ),
          
          // Word count
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: Colors.grey.shade100,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              '${validation.wordCount} words',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
                color: Colors.grey.shade700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Color _getQualityColor(double score) {
    if (score >= 70) return Colors.green;
    if (score >= 40) return Colors.orange;
    return Colors.red;
  }
}

class EvidenceQualityIndicator extends StatelessWidget {
  final EvidenceValidationResponse validation;

  const EvidenceQualityIndicator({
    Key? key,
    required this.validation,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          // Quality score
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      'Evidence Quality: ${validation.qualityScore.toInt()}%',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        color: _getQualityColor(validation.qualityScore),
                        fontSize: 12,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Icon(
                      validation.isSufficient ? Icons.check_circle : Icons.warning,
                      color: validation.isSufficient ? Colors.green : Colors.orange,
                      size: 16,
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                LinearProgressIndicator(
                  value: validation.qualityScore / 100,
                  backgroundColor: Colors.grey.shade200,
                  valueColor: AlwaysStoppedAnimation<Color>(
                    _getQualityColor(validation.qualityScore),
                  ),
                ),
              ],
            ),
          ),
          
          // Count vs ideal
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: validation.isSufficient ? Colors.green.shade100 : Colors.orange.shade100,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              'Count: ${validation.idealCount}',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
                color: validation.isSufficient ? Colors.green.shade700 : Colors.orange.shade700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Color _getQualityColor(double score) {
    if (score >= 70) return Colors.green;
    if (score >= 40) return Colors.orange;
    return Colors.red;
  }
}

class LocationQualityIndicator extends StatelessWidget {
  final double? gpsAccuracy;
  final double? movementSpeed;

  const LocationQualityIndicator({
    Key? key,
    this.gpsAccuracy,
    this.movementSpeed,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    if (gpsAccuracy == null) {
      return Container(
        margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.red.shade50,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          children: [
            Icon(Icons.location_off, color: Colors.red.shade700, size: 20),
            const SizedBox(width: 8),
            Text(
              'No GPS signal',
              style: TextStyle(
                color: Colors.red.shade700,
                fontWeight: FontWeight.w600,
                fontSize: 12,
              ),
            ),
          ],
        ),
      );
    }

    Color accuracyColor = _getAccuracyColor(gpsAccuracy!);
    String accuracyText = '${gpsAccuracy!.toInt()}m';
    
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          Icon(
            Icons.location_on,
            color: accuracyColor,
            size: 20,
          ),
          const SizedBox(width: 8),
          Text(
            'GPS: $accuracyText',
            style: TextStyle(
              color: accuracyColor,
              fontWeight: FontWeight.w600,
              fontSize: 12,
            ),
          ),
          if (movementSpeed != null && movementSpeed! > 5) ...[
            const SizedBox(width: 16),
            Icon(
              Icons.directions_walk,
              color: Colors.orange,
              size: 16,
            ),
            const SizedBox(width: 4),
            Text(
              'Moving',
              style: TextStyle(
                color: Colors.orange,
                fontWeight: FontWeight.w600,
                fontSize: 12,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Color _getAccuracyColor(double accuracy) {
    if (accuracy <= 20) return Colors.green;
    if (accuracy <= 50) return Colors.orange;
    return Colors.red;
  }
}

class GuidanceSummaryCard extends StatelessWidget {
  final GuidanceResponse guidance;

  const GuidanceSummaryCard({
    Key? key,
    required this.guidance,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.all(16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Summary',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              guidance.summary,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            
            if (guidance.priorityActions.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                'Priority Actions',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 8),
              ...guidance.priorityActions.take(3).map((action) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '• ',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        action,
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                  ],
                ),
              )),
            ],
          ],
        ),
      ),
    );
  }
}
