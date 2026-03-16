import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../widgets/musanze_map_painter.dart';
import '../models/musanze_map_data.dart';
import '../services/api_service.dart';
import '../services/device_service.dart';
import '../services/location_service.dart';
import '../services/ml_service.dart';
import '../models/report_model.dart';
import 'notifications_screen.dart';
import 'report_detail_screen.dart';
import 'main_shell.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _apiService = ApiService();
  final _deviceService = DeviceService();
  final _locationService = LocationService();
  final _mlService = MLService();

  String? _deviceId;
  List<ReportListItem> _recentReports = [];
  bool _loading = true;
  int _totalReports = 0;
  int _verifiedReports = 0;
  double _trustScore = 0;
  MusanzeMapData? _mapData;

  // GPS location state
  double? _userLat;
  double? _userLng;
  VillageLocation? _userVillage;
  String? _locationError;

  // ML-related state
  Map<String, MLPrediction> _mlPredictions = {};
  List<MLInsight> _mlInsights = [];
  double _mlTrustScore = 0;
  String _mlStatus = 'Loading...';

  // Hotspot data for sector-level overview
  List<Map<String, dynamic>> _sectorHotspots = [];
  bool _loadingHotspots = true;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() => _loading = true);
    // Load map data in parallel
    MusanzeMapData.load().then((data) {
      if (mounted) setState(() => _mapData = data);
    }).catchError((_) {});

    // Get user GPS location and village
    _locationService.getFullLocation().then((result) {
      if (!mounted) return;
      if (result.hasPosition) {
        setState(() {
          _userLat = result.latitude;
          _userLng = result.longitude;
          _userVillage = result.village;
          _locationError = null;
        });
      } else {
        setState(() {
          _locationError = result.error;
        });
      }
    }).catchError((_) {});

    // Load sector-level hotspots for overview
    _loadSectorHotspots();

    final deviceId = await _deviceService.ensureDeviceId(apiService: _apiService);
    if (deviceId == null || deviceId.isEmpty) {
      setState(() {
        _loading = false;
        _deviceId = null;
        _locationError ??= 'Could not register this device with server.';
      });
      return;
    }
    _deviceId = deviceId;
    try {
      final list = await _apiService.getMyReports(deviceId);
      final reports = list
          .map((e) => ReportListItem.fromJson(e as Map<String, dynamic>))
          .toList();
      final verified = reports
          .where((r) =>
              r.ruleStatus == 'confirmed' ||
              r.ruleStatus == 'verified' ||
              r.ruleStatus == 'trusted')
          .length;

      // Load ML predictions for recent reports
      final reportIds = reports.take(3).map((r) => r.reportId).toList();
      final mlPredictions = await _mlService.getBatchPredictions(reportIds, deviceId);
      
      // Load ML insights for home screen
      final mlInsights = await _mlService.getHomeInsights(deviceId);
      
      // Calculate ML trust score from predictions
      double mlTrustScore = 0;
      if (mlPredictions.isNotEmpty) {
        final totalScore = mlPredictions.values
            .map((p) => p.trustScore)
            .reduce((a, b) => a + b);
        mlTrustScore = totalScore / mlPredictions.length;
      }

      setState(() {
        _recentReports = reports.take(3).toList();
        _totalReports = reports.length;
        _verifiedReports = verified;
        _trustScore = reports.isEmpty
            ? 50
            : ((verified / reports.length) * 100).clamp(0, 100);
        _mlPredictions = mlPredictions;
        _mlInsights = mlInsights;
        _mlTrustScore = mlTrustScore;
        _mlStatus = mlPredictions.isNotEmpty ? 'ML Analysis Complete' : 'No ML Data';
        _loading = false;
      });
    } catch (e) {
      debugPrint('Failed to load reports on home: $e');
      setState(() => _loading = false);
    }
  }

  Future<void> _loadSectorHotspots() async {
    try {
      final hotspots = await _apiService.getPublicHotspots();
      if (mounted) {
        setState(() {
          _sectorHotspots = hotspots.cast<Map<String, dynamic>>();
          _loadingHotspots = false;
        });
      }
    } catch (e) {
      debugPrint('Failed to load hotspots: $e');
      if (mounted) {
        setState(() => _loadingHotspots = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _loadData,
          color: AppColors.accent,
          child: CustomScrollView(
            slivers: [
              SliverToBoxAdapter(child: _buildHeader()),
              SliverPadding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                sliver: SliverList(
                  delegate: SliverChildListDelegate([
                    _buildTrustScoreCard(),
                    const SizedBox(height: 4),
                    _buildStatsGrid(),
                    if (_mlInsights.isNotEmpty) ...[
                      const SizedBox(height: 11),
                      const SectionHeader('AI Insights'),
                      _buildMLInsights(),
                    ],
                    const SectionHeader('Safety Overview'),
                    _buildMapPreview(),
                    const SizedBox(height: 11),
                    const SectionHeader('Recent Near You'),
                    if (_loading)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 40),
                        child: Center(
                            child: CircularProgressIndicator(
                                color: AppColors.accent)),
                      )
                    else if (_recentReports.isEmpty)
                      _buildEmptyState()
                    else
                      ..._recentReports.map(_buildReportItem),
                    const SizedBox(height: 24),
                  ]),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _userVillage != null
                      ? '${_userVillage!.village}, ${_userVillage!.cell}'
                      : (_userLat != null && _userLng != null)
                          ? '${_userLat!.toStringAsFixed(5)}, ${_userLng!.toStringAsFixed(5)}'
                          : (_locationError ?? 'Detecting current location...'),
                  style: const TextStyle(fontSize: 11, color: AppColors.muted)),
                RichText(
                  text: _userVillage != null
                      ? const TextSpan(
                          style:
                              TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
                          children: [
                            TextSpan(
                                text: 'Musanze ',
                                style: TextStyle(color: AppColors.text)),
                            TextSpan(
                                text: 'District',
                                style: TextStyle(color: AppColors.accent)),
                          ],
                        )
                      : const TextSpan(
                          style:
                              TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
                          children: [
                            TextSpan(
                                text: 'Location ',
                                style: TextStyle(color: AppColors.text)),
                            TextSpan(
                                text: 'Unknown',
                                style: TextStyle(color: AppColors.warn)),
                          ],
                        ),
                ),
              ],
            ),
          ),
          GestureDetector(
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(
                  builder: (_) => const NotificationsScreen()),
            ),
            child: Stack(
              children: [
                const Text('🔔', style: TextStyle(fontSize: 22)),
                Positioned(
                  top: -1,
                  right: -2,
                  child: Container(
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: AppColors.danger,
                      shape: BoxShape.circle,
                      border: Border.all(color: AppColors.bg, width: 1.5),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTrustScoreCard() {
    // Use ML trust score if available, otherwise fall back to rule-based score
    final displayScore = _mlTrustScore > 0 ? _mlTrustScore : _trustScore;
    final isMLBased = _mlTrustScore > 0;
    
    return Container(
      padding: const EdgeInsets.all(15),
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            isMLBased 
                ? AppColors.accent.withValues(alpha: 0.15)
                : AppColors.accent.withValues(alpha: 0.1),
            isMLBased
                ? AppColors.accent2.withValues(alpha: 0.08)
                : AppColors.accent2.withValues(alpha: 0.05),
          ],
        ),
        border: Border.all(
            color: isMLBased 
                ? AppColors.accent.withValues(alpha: 0.4)
                : AppColors.accent.withValues(alpha: 0.28)
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          TrustScoreRing(score: displayScore),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      isMLBased ? 'ML TRUST SCORE' : 'DEVICE TRUST SCORE',
                      style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.muted,
                          letterSpacing: 0.8),
                    ),
                    if (isMLBased) ...[
                      const SizedBox(width: 4),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                        decoration: BoxDecoration(
                          color: AppColors.accent.withValues(alpha: 0.2),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          'AI',
                          style: TextStyle(
                            fontSize: 8,
                            color: AppColors.accent,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Row(
                  children: [
                    Text(
                      displayScore >= 70
                          ? 'Excellent'
                          : displayScore >= 40
                              ? 'Moderate'
                              : 'Needs Improvement',
                      style: const TextStyle(
                          fontSize: 14, fontWeight: FontWeight.w600),
                    ),
                    if (displayScore >= 50)
                      Text(isMLBased ? ' 🤖' : ' ↑',
                          style: TextStyle(color: AppColors.accent)),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  '$_totalReports reports · $_verifiedReports verified',
                  style: const TextStyle(fontSize: 10, color: AppColors.muted),
                ),
                if (isMLBased) ...[
                  const SizedBox(height: 1),
                  Text(
                    _mlStatus,
                    style: const TextStyle(fontSize: 9, color: AppColors.accent),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatsGrid() {
    return Row(
      children: [
        Expanded(
            child: StatBox(
                value: '$_totalReports',
                label: 'My Reports',
                valueColor: AppColors.ok)),
        const SizedBox(width: 9),
        Expanded(
            child: StatBox(
                value: '${_mapData?.sectors.length ?? 15}',
                label: 'Sectors',
                valueColor: AppColors.warn)),
      ],
    );
  }

  Widget _buildMapPreview() {
    return GestureDetector(
      onTap: () {
        // Open the Map tab inside the main shell so the bottom nav stays visible.
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => const MainShell(initialIndex: 1),
          ),
        );
      },
      child: Container(
        height: 180,
        decoration: BoxDecoration(
          color: AppColors.surface2,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(14),
        ),
        clipBehavior: Clip.antiAlias,
        child: Stack(
          children: [
            if (_mapData != null)
              CustomPaint(
                size: Size.infinite,
                painter: MusanzeMapPreviewPainter(
                  mapData: _mapData!,
                  userLatitude: _userLat,
                  userLongitude: _userLng,
                  userVillage: _userVillage,
                  sectorHotspots: _sectorHotspots,
                ),
              )
            else
              const Center(
                  child: CircularProgressIndicator(
                      color: AppColors.accent, strokeWidth: 2)),
            Positioned(
              bottom: 8,
              left: 10,
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                decoration: BoxDecoration(
                  color: AppColors.bg.withValues(alpha: 0.85),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  _userVillage != null
                      ? '📍 ${_userVillage!.village}, ${_userVillage!.sector}'
                    : (_userLat != null && _userLng != null)
                      ? '📍 Current GPS location detected'
                      : '📍 Detecting current location... · ${_mapData?.sectors.length ?? 0} sectors',
                  style: const TextStyle(
                      fontSize: 9,
                      color: AppColors.muted,
                      fontFamily: 'monospace'),
                ),
              ),
            ),
            Positioned(
              top: 9,
              right: 9,
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
                decoration: BoxDecoration(
                  color: AppColors.bg.withValues(alpha: 0.8),
                  borderRadius: BorderRadius.circular(7),
                ),
                child: const Text(
                  'Tap to expand →',
                  style: TextStyle(fontSize: 9, color: AppColors.accent),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildReportItem(ReportListItem report) {
    final icon = iconForIncidentType(report.incidentTypeName ?? '');
    final bgColor = colorForIncidentType(report.incidentTypeName ?? '');
    final mlPrediction = _mlPredictions[report.reportId];
    
    return ReportItemCard(
      icon: icon,
      iconBg: bgColor.withValues(alpha: 0.1),
      typeName: report.incidentTypeName ?? 'Incident',
      description: report.description ?? 'No description',
      timeLabel: timeAgo(report.reportedAt),
      statusLabel: mlPrediction != null 
          ? '${mlPrediction.statusEmoji} ${mlPrediction.statusText}'
          : formatStatus(report.ruleStatus),
      statusType: mlPrediction != null 
          ? _getMLBadgeType(mlPrediction.predictionLabel)
          : badgeTypeFromStatus(report.ruleStatus),
      reportNumber: report.reportNumber,
      trustScore: report.trustScore ?? mlPrediction?.trustScore,
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => ReportDetailScreen(
            reportId: report.reportId,
            deviceId: _deviceId ?? '',
          ),
        ),
      ),
    );
  }

  BadgeType _getMLBadgeType(String predictionLabel) {
    switch (predictionLabel) {
      case 'likely_real':
        return BadgeType.ok;
      case 'suspicious':
        return BadgeType.warn;
      case 'fake':
        return BadgeType.err;
      default:
        return BadgeType.info;
    }
  }

  Widget _buildMLInsights() {
    if (_mlInsights.isEmpty) return const SizedBox.shrink();
    
    return Column(
      children: _mlInsights.take(3).map((insight) => Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.surface2,
          border: Border.all(color: AppColors.border.withValues(alpha: 0.5)),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(
                color: _getInsightColor(insight.type).withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                _getInsightEmoji(insight.type),
                style: const TextStyle(fontSize: 16),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    insight.title,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: AppColors.text,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    insight.description,
                    style: const TextStyle(
                      fontSize: 10,
                      color: AppColors.muted,
                    ),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            if (insight.score != null) ...[
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: _getScoreColor(insight.score!).withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  '${insight.score!.toInt()}%',
                  style: TextStyle(
                    fontSize: 9,
                    color: _getScoreColor(insight.score!),
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ],
        ),
      )).toList(),
    );
  }

  Color _getInsightColor(String type) {
    switch (type) {
      case 'trust':
        return AppColors.accent;
      case 'safety':
        return AppColors.ok;
      case 'pattern':
        return AppColors.warn;
      default:
        return AppColors.muted;
    }
  }

  String _getInsightEmoji(String type) {
    switch (type) {
      case 'trust':
        return '🤖';
      case 'safety':
        return '🛡️';
      case 'pattern':
        return '📊';
      default:
        return '💡';
    }
  }

  Color _getScoreColor(double score) {
    if (score >= 70) return AppColors.ok;
    if (score >= 40) return AppColors.warn;
    return AppColors.danger;
  }

  Widget _buildEmptyState() {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 40),
      alignment: Alignment.center,
      child: Column(
        children: [
          Icon(Icons.shield_outlined,
              size: 48, color: AppColors.muted.withValues(alpha: 0.5)),
          const SizedBox(height: 12),
          const Text('No reports yet',
              style: TextStyle(color: AppColors.muted, fontSize: 14)),
          const SizedBox(height: 4),
          const Text('Tap + to submit your first report',
              style: TextStyle(color: AppColors.muted, fontSize: 11)),
        ],
      ),
    );
  }

}
