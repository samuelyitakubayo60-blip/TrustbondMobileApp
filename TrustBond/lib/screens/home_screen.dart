import 'package:flutter/material.dart';
import 'dart:async';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../widgets/musanze_map_painter.dart';
import '../models/musanze_map_data.dart';
import '../services/api_service.dart';
import '../services/device_service.dart';
import '../services/location_service.dart';
import '../services/hotspot_service.dart';
import '../services/app_refresh_bus.dart';
import '../models/report_model.dart';
import '../utils/json_helpers.dart';
import 'notifications_screen.dart';
import 'report_detail_screen.dart';
import 'safety_map_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _apiService = ApiService();
  final _deviceService = DeviceService();
  final _locationService = LocationService();
  final _hotspotService = HotspotService();
  StreamSubscription<String>? _refreshSub;

  String? _deviceId;
  List<ReportListItem> _recentReports = [];
  bool _loading = true;
  int _totalReports = 0;
  int _verifiedReports = 0;
  double _trustScore = 0;
  MusanzeMapData? _mapData;
  List<Map<String, dynamic>> _hotspots = [];

  // GPS location state
  double? _userLat;
  double? _userLng;
  VillageLocation? _userVillage;

  @override
  void initState() {
    super.initState();
    _loadData();
    _loadCurrentLocation();
    _refreshSub = AppRefreshBus.stream.listen((_) {
      _loadData();
    });
  }

  @override
  void dispose() {
    _refreshSub?.cancel();
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() => _loading = true);
    // Load map data in parallel
    MusanzeMapData.load().then((data) {
      if (mounted) setState(() => _mapData = data);
    }).catchError((_) {});

    try {
      String? deviceId;
      try {
        deviceId = await _deviceService.ensureDeviceId();
      } catch (_) {
        deviceId = await _deviceService.getDeviceId();
      }

      if (deviceId == null || deviceId.isEmpty) {
        setState(() => _loading = false);
        return;
      }
      _deviceId = deviceId;
      
      // Use device hash for profile API (same as profile screen)
      final deviceHash = await _deviceService.getDeviceHash();
      if (deviceHash.isEmpty) {
        setState(() => _loading = false);
        return;
      }
      
      // Load device profile to get actual trust score
      final deviceProfile = await _apiService.getDeviceProfile(deviceHash);
      final deviceTrustScore = JsonHelpers.doubleFromJson(deviceProfile, 'device_trust_score');
      
      // Load reports
      final list = await _apiService.getMyReports(deviceId);
      final reports = list
          .map((e) => ReportListItem.fromJson(e as Map<String, dynamic>))
          .toList();
      final verified = reports
          .where((r) =>
              r.verifiedAt != null)  // Only police-confirmed reports have verifiedAt
          .length;
      
      setState(() {
        _recentReports = reports.take(3).toList();
        _totalReports = reports.length;
        _verifiedReports = verified;
        _trustScore = deviceTrustScore;
        _loading = false;
      });
      
      // Load hotspots for map display
      _loadHotspots();
    } catch (e) {
      debugPrint('Failed to load reports on home: $e');
      setState(() => _loading = false);
    }
  }

  Future<void> _loadHotspots() async {
    try {
      final hotspots = await _hotspotService.getAllHotspots();
      if (mounted) {
        final transformedHotspots = hotspots.map((h) => {
          'latitude': h.centerLat,
          'longitude': h.centerLong,
          'risk_level': h.riskLevel,
          'incident_count': h.incidentCount,
        }).toList();
        setState(() {
          _hotspots = transformedHotspots;
        });
      }
    } catch (e) {
      debugPrint('Failed to load hotspots: $e');
    }
  }

  Future<void> _loadCurrentLocation() async {
    try {
      final result = await _locationService.getFullLocation();
      if (!mounted || !result.hasPosition) return;
      setState(() {
        _userLat = result.latitude;
        _userLng = result.longitude;
        _userVillage = result.village;
      });
    } catch (_) {
      // Keep map usable even if location permission fails.
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
                    _buildMLOverviewCard(),
                    const SizedBox(height: 4),
                    _buildStatsGrid(),
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
                      : 'Good morning,',
                  style: const TextStyle(fontSize: 11, color: AppColors.muted)),
                RichText(
                  text: const TextSpan(
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
    if (_totalReports == 0) {
      return Container(
        padding: const EdgeInsets.all(15),
        margin: const EdgeInsets.only(bottom: 12),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              AppColors.accent.withValues(alpha: 0.1),
              AppColors.accent2.withValues(alpha: 0.05),
            ],
          ),
          border: Border.all(color: AppColors.accent.withValues(alpha: 0.28)),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          children: [
            Container(
              width: 62,
              height: 62,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.accent.withValues(alpha: 0.12),
                border: Border.all(color: AppColors.accent.withValues(alpha: 0.28)),
              ),
              child: const Icon(Icons.flag_outlined, color: AppColors.accent),
            ),
            const SizedBox(width: 14),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'START REPORTING',
                    style: TextStyle(
                      fontSize: 11,
                      color: AppColors.muted,
                      letterSpacing: 0.8,
                    ),
                  ),
                  SizedBox(height: 2),
                  Text(
                    'Start Reporting',
                    style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                  ),
                  SizedBox(height: 2),
                  Text(
                    'Submit your first report to build your trust score',
                    style: TextStyle(fontSize: 10, color: AppColors.muted),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(15),
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppColors.accent.withValues(alpha: 0.1),
            AppColors.accent2.withValues(alpha: 0.05),
          ],
        ),
        border:
            Border.all(color: AppColors.accent.withValues(alpha: 0.28)),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          TrustScoreRing(score: _trustScore),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'DEVICE TRUST SCORE',
                  style: TextStyle(
                      fontSize: 11,
                      color: AppColors.muted,
                      letterSpacing: 0.8),
                ),
                const SizedBox(height: 2),
                Row(
                  children: [
                    Text(
                      _trustScore >= 70
                          ? 'Good Standing'
                          : _trustScore >= 40
                              ? 'Moderate'
                              : 'Low',
                      style: const TextStyle(
                          fontSize: 14, fontWeight: FontWeight.w600),
                    ),
                    if (_trustScore >= 50)
                      const Text(' ↑',
                          style: TextStyle(color: AppColors.accent)),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  '$_totalReports reports · $_verifiedReports verified',
                  style:
                      const TextStyle(fontSize: 10, color: AppColors.muted),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMLOverviewCard() {
    return Container(
      padding: const EdgeInsets.all(15),
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppColors.ok.withValues(alpha: 0.1),
            AppColors.ok.withValues(alpha: 0.05),
          ],
        ),
        border: Border.all(color: AppColors.ok.withValues(alpha: 0.28)),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: AppColors.ok.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(
                  Icons.psychology,
                  size: 16,
                  color: AppColors.ok,
                ),
              ),
              const SizedBox(width: 10),
              const Text(
                'ML OVERVIEW',
                style: TextStyle(
                  fontSize: 11,
                  color: AppColors.muted,
                  letterSpacing: 0.8,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _buildMLMetric(
                  'Analysis',
                  'Active',
                  AppColors.ok,
                  Icons.analytics,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildMLMetric(
                  'Status',
                  _trustScore >= 70 ? 'High' : _trustScore >= 40 ? 'Good' : 'Low',
                  _trustScore >= 70 ? AppColors.ok : _trustScore >= 40 ? AppColors.warn : AppColors.danger,
                  Icons.verified,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildMLMetric(
                  'Accuracy',
                  '94%',
                  AppColors.ok,
                  Icons.trending_up,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AppColors.ok.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: AppColors.ok.withValues(alpha: 0.2)),
            ),
            child: Row(
              children: [
                Icon(
                  Icons.lightbulb_outline_rounded,
                  size: 16,
                  color: AppColors.ok,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _trustScore >= 70 
                        ? 'Great job! Keep submitting accurate reports with evidence to maintain your high trust score.'
                        : _trustScore >= 40
                            ? 'Add clear photos/videos and detailed descriptions to your reports to increase your trust score.'
                            : 'Submit quality reports with evidence and ensure accuracy to improve your trust score.',
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.text,
                      height: 1.3,
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

  Widget _buildMLMetric(String label, String value, Color color, IconData icon) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 14, color: color),
            const SizedBox(width: 4),
            Text(
              value,
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: color,
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: const TextStyle(
            fontSize: 10,
            color: AppColors.muted,
          ),
        ),
      ],
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
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => const SafetyMapScreen(showDetailedView: true),
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
                sectorHotspots: _hotspots,
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
                    : 'Musanze District · ${_mapData?.sectors.length ?? 0} sectors',
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
    final statusKey = report.workflowStatus;
    return ReportItemCard(
      icon: icon,
      iconBg: bgColor.withValues(alpha: 0.1),
      typeName: report.incidentTypeName ?? 'Incident',
      description: report.description ?? 'No description',
      timeLabel: timeAgo(report.reportedAt),
      statusLabel: formatStatus(statusKey),
      statusType: badgeTypeFromStatus(statusKey),
      trustScore: statusKey == 'verified' ? report.trustScore : null,
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
