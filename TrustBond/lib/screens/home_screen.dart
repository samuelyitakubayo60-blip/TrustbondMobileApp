import 'dart:math';
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
import 'report_step1_screen.dart';

// ── Haversine distance helper ─────────────────────────────────────────────────
double _haversineKm(double lat1, double lon1, double lat2, double lon2) {
  const r = 6371.0;
  final dLat = (lat2 - lat1) * pi / 180;
  final dLon = (lon2 - lon1) * pi / 180;
  final a = sin(dLat / 2) * sin(dLat / 2) +
      cos(lat1 * pi / 180) *
          cos(lat2 * pi / 180) *
          sin(dLon / 2) *
          sin(dLon / 2);
  return r * 2 * atan2(sqrt(a), sqrt(1 - a));
}

// ── Risk helpers ──────────────────────────────────────────────────────────────
Color _riskColor(String level) {
  switch (level.toLowerCase()) {
    case 'critical':
      return const Color(0xFFFF3B5C);
    case 'active':
    case 'high':
      return const Color(0xFFFF6B35);
    case 'emerging':
    case 'medium':
      return const Color(0xFFFFBB00);
    case 'low_activity':
    case 'low':
      return const Color(0xFF00C896);
    default:
      return AppColors.muted;
  }
}

String _riskLabel(String level) {
  switch (level.toLowerCase()) {
    case 'critical':
      return 'CRITICAL RISK';
    case 'active':
    case 'high':
      return 'HIGH RISK';
    case 'emerging':
    case 'medium':
      return 'MODERATE RISK';
    case 'low_activity':
    case 'low':
      return 'LOW RISK';
    default:
      return 'UNKNOWN';
  }
}

String _riskIcon(String level) {
  switch (level.toLowerCase()) {
    case 'critical':
      return '🔴';
    case 'active':
    case 'high':
      return '🟠';
    case 'emerging':
    case 'medium':
      return '🟡';
    case 'low_activity':
    case 'low':
      return '🟢';
    default:
      return '⚪';
  }
}

String _safetyMessage(String level, String? crimeType) {
  final crime = crimeType ?? 'incidents';
  switch (level.toLowerCase()) {
    case 'critical':
      return 'A critical $crime hotspot is active near you. Avoid the area, stay indoors if possible, and report any suspicious activity immediately.';
    case 'active':
    case 'high':
      return 'Elevated $crime activity detected nearby. Remain alert, travel in groups, and report anything suspicious right away.';
    case 'emerging':
    case 'medium':
      return 'Emerging $crime patterns detected in your area. Stay aware of your surroundings and report any unusual activity.';
    case 'low_activity':
    case 'low':
      return 'Your area is relatively safe. Continue staying alert and report any incidents you witness to help keep Musanze safe.';
    default:
      return 'Stay alert and report any suspicious activity to help keep your community safe.';
  }
}

class HomeScreen extends StatefulWidget {
  final VoidCallback? onOpenMapTab;

  const HomeScreen({super.key, this.onOpenMapTab});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen>
    with SingleTickerProviderStateMixin {
  final _apiService = ApiService();
  final _deviceService = DeviceService();
  final _locationService = LocationService();
  final _hotspotService = HotspotService();
  StreamSubscription<String>? _refreshSub;

  // Data
  String? _deviceId;
  List<ReportListItem> _recentReports = [];
  bool _loading = true;
  int _totalReports = 0;
  int _verifiedReports = 0;
  double _trustScore = 0;
  MusanzeMapData? _mapData;
  List<Map<String, dynamic>> _hotspots = [];

  // Location
  double? _userLat;
  double? _userLng;
  VillageLocation? _userVillage;

  // Safety / Nearby
  double _selectedRadiusKm = 1.0;
  List<Hotspot> _nearbyHotspots = [];
  bool _loadingHotspots = false;

  // Animation
  late AnimationController _pulseController;
  late Animation<double> _pulseAnim;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);
    _pulseAnim = Tween<double>(begin: 0.85, end: 1.0).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );

    _loadData();
    _loadCurrentLocation();
    _refreshSub = AppRefreshBus.stream.listen((_) => _loadData());
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _refreshSub?.cancel();
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() => _loading = true);
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

      final deviceHash = await _deviceService.getDeviceHash();
      if (deviceHash.isEmpty) {
        setState(() => _loading = false);
        return;
      }

      List<ReportListItem> reports = [];
      double deviceTrustScore = 0;

      try {
        final deviceProfile = await _apiService.getDeviceProfile(deviceHash);
        deviceTrustScore =
            JsonHelpers.doubleFromJson(deviceProfile, 'device_trust_score');
        final list = await _apiService.getMyReports(deviceId);
        reports = list
            .map((e) => ReportListItem.fromJson(e as Map<String, dynamic>))
            .toList();
      } catch (e) {
        debugPrint('Online load failed, using cache: $e');
        try {
          final cached = await _apiService.getDeviceProfile(deviceHash);
          deviceTrustScore =
              JsonHelpers.doubleFromJson(cached, 'device_trust_score');
        } catch (_) {
          deviceTrustScore = 50.0;
        }
        try {
          final list = await _apiService.getMyReports(deviceId);
          reports = list
              .map((e) => ReportListItem.fromJson(e as Map<String, dynamic>))
              .toList();
        } catch (_) {}
      }

      final verified = reports.where((r) => r.verifiedAt != null).length;

      setState(() {
        _recentReports = reports.take(3).toList();
        _totalReports = reports.length;
        _verifiedReports = verified;
        _trustScore = deviceTrustScore;
        _loading = false;
      });

      _loadAllHotspots();
    } catch (e) {
      debugPrint('Failed to load home data: $e');
      setState(() => _loading = false);
    }
  }

  Future<void> _loadAllHotspots() async {
    try {
      final hotspots = await _hotspotService.getAllHotspots();
      if (!mounted) return;
      final transformed = hotspots.map((h) => {
            'latitude': h.centerLat,
            'longitude': h.centerLong,
            'risk_level': h.riskLevel,
            'incident_count': h.incidentCount,
          }).toList();
      setState(() => _hotspots = transformed);
      _updateNearbyHotspots(hotspots);
    } catch (e) {
      debugPrint('Failed to load hotspots: $e');
    }
  }

  void _updateNearbyHotspots(List<Hotspot> all) {
    if (_userLat == null || _userLng == null) return;
    final nearby = all.where((h) {
      final d = _haversineKm(
          _userLat!, _userLng!, h.centerLat, h.centerLong);
      return d <= _selectedRadiusKm;
    }).toList();
    // Sort by risk severity then distance
    nearby.sort((a, b) {
      final riskOrder = _riskOrder(b.riskLevel) - _riskOrder(a.riskLevel);
      if (riskOrder != 0) return riskOrder;
      final dA = _haversineKm(
          _userLat!, _userLng!, a.centerLat, a.centerLong);
      final dB = _haversineKm(
          _userLat!, _userLng!, b.centerLat, b.centerLong);
      return dA.compareTo(dB);
    });
    setState(() => _nearbyHotspots = nearby);
  }

  int _riskOrder(String level) {
    switch (level.toLowerCase()) {
      case 'critical':
        return 4;
      case 'active':
      case 'high':
        return 3;
      case 'emerging':
      case 'medium':
        return 2;
      case 'low_activity':
      case 'low':
        return 1;
      default:
        return 0;
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
      // Re-filter after getting location
      if (_hotspots.isNotEmpty) {
        setState(() => _loadingHotspots = true);
        _hotspotService.getAllHotspots().then((all) {
          _updateNearbyHotspots(all);
          if (mounted) setState(() => _loadingHotspots = false);
        });
      }
    } catch (_) {}
  }

  Future<void> _onRadiusChanged(double km) async {
    setState(() {
      _selectedRadiusKm = km;
      _loadingHotspots = true;
    });
    try {
      final all = await _hotspotService.getAllHotspots();
      _updateNearbyHotspots(all);
    } catch (_) {}
    if (mounted) setState(() => _loadingHotspots = false);
  }

  // ── Build ───────────────────────────────────────────────────────────────────

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
                padding: const EdgeInsets.symmetric(horizontal: 20),
                sliver: SliverList(
                  delegate: SliverChildListDelegate([
                    _buildTrustScoreCard(),
                    const SizedBox(height: 6),
                    _buildStatsGrid(),
                    const SizedBox(height: 18),
                    _buildSafetyAlertSection(),
                    const SizedBox(height: 18),
                    _buildSafetyTips(),
                    const SizedBox(height: 18),
                    _buildMapSection(),
                    const SizedBox(height: 20),
                    _buildRecentSection(),
                    const SizedBox(height: 28),
                  ]),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ── Header ──────────────────────────────────────────────────────────────────

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 14, 20, 18),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            AppColors.surface.withValues(alpha: 0.95),
            AppColors.bg.withValues(alpha: 0.0),
          ],
        ),
      ),
      child: Row(
        children: [
          // Shield icon
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  AppColors.accent.withValues(alpha: 0.22),
                  AppColors.accent2.withValues(alpha: 0.12),
                ],
              ),
              borderRadius: BorderRadius.circular(11),
              border: Border.all(
                  color: AppColors.accent.withValues(alpha: 0.35)),
            ),
            child: const Icon(Icons.shield_rounded,
                size: 18, color: AppColors.accent),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _userVillage != null
                      ? '${_userVillage!.village}, ${_userVillage!.cell}'
                      : 'Musanze District',
                  style: const TextStyle(
                      fontSize: 11, color: AppColors.muted),
                ),
                const Text(
                  'TrustBond Safety',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: AppColors.text,
                  ),
                ),
              ],
            ),
          ),
          GestureDetector(
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const NotificationsScreen()),
            ),
            child: Stack(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: AppColors.surface2,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: AppColors.border),
                  ),
                  child: const Icon(Icons.notifications_outlined,
                      size: 20, color: AppColors.text),
                ),
                Positioned(
                  top: 8,
                  right: 8,
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

  // ── Trust Score Card ────────────────────────────────────────────────────────

  Widget _buildTrustScoreCard() {
    final scoreColor = _trustScore >= 70
        ? AppColors.ok
        : _trustScore >= 40
            ? AppColors.warn
            : AppColors.danger;

    return Container(
      padding: const EdgeInsets.all(16),
      margin: const EdgeInsets.only(bottom: 4),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            scoreColor.withValues(alpha: 0.12),
            AppColors.surface2.withValues(alpha: 0.9),
          ],
        ),
        border: Border.all(color: scoreColor.withValues(alpha: 0.30)),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        children: [
          TrustScoreRing(score: _trustScore, color: scoreColor),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'TRUST SCORE',
                  style: TextStyle(
                      fontSize: 10,
                      color: AppColors.muted,
                      letterSpacing: 1.0),
                ),
                const SizedBox(height: 3),
                Text(
                  _trustScore >= 70
                      ? 'Good Standing'
                      : _trustScore >= 40
                          ? 'Moderate'
                          : 'Needs Improvement',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: scoreColor,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '${_trustScore.toStringAsFixed(1)} / 100 · $_totalReports reports · $_verifiedReports verified',
                  style: const TextStyle(
                      fontSize: 10, color: AppColors.muted),
                ),
              ],
            ),
          ),
          Icon(
            _trustScore >= 70
                ? Icons.trending_up_rounded
                : _trustScore >= 40
                    ? Icons.trending_flat_rounded
                    : Icons.trending_down_rounded,
            color: scoreColor,
            size: 22,
          ),
        ],
      ),
    );
  }

  // ── Stats Grid ──────────────────────────────────────────────────────────────

  Widget _buildStatsGrid() {
    return Row(
      children: [
        Expanded(
          child: _StatCard(
            value: '$_totalReports',
            label: 'My Reports',
            icon: Icons.article_outlined,
            color: AppColors.accent,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _StatCard(
            value: '$_verifiedReports',
            label: 'Verified',
            icon: Icons.verified_outlined,
            color: AppColors.ok,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _StatCard(
            value: '${_nearbyHotspots.length}',
            label: 'Nearby Alerts',
            icon: Icons.warning_amber_rounded,
            color: _nearbyHotspots.isEmpty
                ? AppColors.muted
                : _riskColor(_nearbyHotspots.first.riskLevel),
          ),
        ),
      ],
    );
  }

  // ── Safety Alert Section ────────────────────────────────────────────────────

  Widget _buildSafetyAlertSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.location_on_rounded,
                size: 15, color: AppColors.accent),
            const SizedBox(width: 6),
            const Text(
              'SAFETY NEAR YOU',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: AppColors.muted,
                letterSpacing: 0.9,
              ),
            ),
            const Spacer(),
            if (_loadingHotspots)
              const SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(
                    strokeWidth: 1.5, color: AppColors.accent),
              ),
          ],
        ),
        const SizedBox(height: 10),
        // Distance selector
        _buildDistanceSelector(),
        const SizedBox(height: 12),
        // Alert card
        _buildAlertCard(),
      ],
    );
  }

  Widget _buildDistanceSelector() {
    const radii = [0.5, 1.0, 2.0, 5.0];
    return Row(
      children: radii.map((km) {
        final selected = _selectedRadiusKm == km;
        final label = km < 1.0
            ? '${(km * 1000).toInt()}m'
            : '${km.toStringAsFixed(km == km.toInt() ? 0 : 1)}km';
        return Padding(
          padding: const EdgeInsets.only(right: 8),
          child: GestureDetector(
            onTap: () => _onRadiusChanged(km),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
              decoration: BoxDecoration(
                color: selected
                    ? AppColors.accent.withValues(alpha: 0.18)
                    : AppColors.surface2,
                borderRadius: BorderRadius.circular(20),
                border: Border.all(
                  color: selected
                      ? AppColors.accent
                      : AppColors.border,
                  width: selected ? 1.5 : 1,
                ),
              ),
              child: Text(
                label,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: selected ? AppColors.accent : AppColors.muted,
                ),
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildAlertCard() {
    if (_userLat == null || _userLng == null) {
      return _NoLocationCard(onOpenMap: widget.onOpenMapTab);
    }

    if (_nearbyHotspots.isEmpty) {
      return _SafeCard(radiusKm: _selectedRadiusKm);
    }

    final top = _nearbyHotspots.first;
    final dist = _haversineKm(
        _userLat!, _userLng!, top.centerLat, top.centerLong);
    final color = _riskColor(top.riskLevel);

    return AnimatedBuilder(
      animation: _pulseAnim,
      builder: (_, child) => Transform.scale(
        scale: top.riskLevel == 'critical' ? _pulseAnim.value : 1.0,
        child: child,
      ),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              color.withValues(alpha: 0.15),
              AppColors.surface2.withValues(alpha: 0.85),
            ],
          ),
          border: Border.all(color: color.withValues(alpha: 0.45)),
          borderRadius: BorderRadius.circular(18),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(_riskIcon(top.riskLevel),
                    style: const TextStyle(fontSize: 20)),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _riskLabel(top.riskLevel),
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w800,
                          color: color,
                          letterSpacing: 0.6,
                        ),
                      ),
                      Text(
                        '${top.incidentTypeName ?? 'Incident'} · ${dist < 1.0 ? '${(dist * 1000).toInt()}m away' : '${dist.toStringAsFixed(1)}km away'}',
                        style: const TextStyle(
                            fontSize: 11, color: AppColors.muted),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 9, vertical: 4),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: color.withValues(alpha: 0.4)),
                  ),
                  child: Text(
                    '${top.incidentCount} reports',
                    style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w600,
                        color: color),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              _safetyMessage(top.riskLevel, top.incidentTypeName),
              style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.text,
                  height: 1.5),
            ),
            if (_nearbyHotspots.length > 1) ...[
              const SizedBox(height: 8),
              Text(
                '+${_nearbyHotspots.length - 1} more hotspot${_nearbyHotspots.length > 2 ? 's' : ''} within ${_selectedRadiusKm < 1 ? '${(_selectedRadiusKm * 1000).toInt()}m' : '${_selectedRadiusKm.toStringAsFixed(_selectedRadiusKm == _selectedRadiusKm.toInt() ? 0 : 1)}km'}',
                style: TextStyle(
                    fontSize: 10,
                    color: color.withValues(alpha: 0.8)),
              ),
            ],
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: GestureDetector(
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(
                          builder: (_) => const ReportStep1Screen()),
                    ),
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      decoration: BoxDecoration(
                        color: color,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      alignment: Alignment.center,
                      child: const Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.report_rounded,
                              size: 14, color: Colors.black),
                          SizedBox(width: 6),
                          Text(
                            'Report Incident',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              color: Colors.black,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: GestureDetector(
                    onTap: widget.onOpenMapTab,
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      decoration: BoxDecoration(
                        color: color.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(12),
                        border:
                            Border.all(color: color.withValues(alpha: 0.4)),
                      ),
                      alignment: Alignment.center,
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.map_rounded, size: 14, color: color),
                          const SizedBox(width: 6),
                          Text(
                            'View on Map',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              color: color,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // ── Safety Tips ─────────────────────────────────────────────────────────────

  static const _fallbackTips = [
    ('🔔', 'Stay Alert', 'Keep aware of your surroundings at all times.'),
    ('📱', 'Report Fast', 'Report incidents quickly — early reports save lives.'),
    ('👥', 'Travel Together', 'Move in groups especially at night or in risky areas.'),
    ('📍', 'Share Location', 'Let trusted contacts know where you are.'),
  ];

  Widget _buildSafetyTips() {
    // Build tip cards from nearby hotspot citizen advisories (LLM-generated).
    // Each advisory is split on ". " so long sentences become separate cards.
    final liveTips = <(String, String, String)>[];
    for (final h in _nearbyHotspots) {
      final advisory = h.citizenAdvisory?.trim() ?? '';
      if (advisory.isEmpty) continue;
      final sentences = advisory
          .split(RegExp(r'\.\s+'))
          .map((s) => s.trim())
          .where((s) => s.length > 10)
          .toList();
      for (final sentence in sentences) {
        final text = sentence.endsWith('.') ? sentence : '$sentence.';
        liveTips.add((_riskIcon(h.riskLevel), h.incidentTypeName ?? 'Advisory', text));
        if (liveTips.length >= 6) break;
      }
      if (liveTips.length >= 6) break;
    }

    final tips = liveTips.isNotEmpty ? liveTips : _fallbackTips;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionLabel('SAFETY RECOMMENDATIONS'),
        const SizedBox(height: 10),
        SizedBox(
          height: 100,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: tips.length,
            separatorBuilder: (context, index) => const SizedBox(width: 10),
            itemBuilder: (_, i) {
              final (icon, title, desc) = tips[i];
              return Container(
                width: 160,
                padding: const EdgeInsets.all(13),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [
                      AppColors.surface2,
                      AppColors.surface3.withValues(alpha: 0.6),
                    ],
                  ),
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(
                      color: AppColors.accent.withValues(alpha: 0.15)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(icon, style: const TextStyle(fontSize: 20)),
                    const SizedBox(height: 6),
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      desc,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontSize: 10, color: AppColors.muted, height: 1.4),
                    ),
                  ],
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  String _riskIcon(String riskLevel) {
    switch (riskLevel.toLowerCase()) {
      case 'critical':
        return '🚨';
      case 'high':
      case 'active':
        return '⚠️';
      case 'medium':
      case 'emerging':
        return '🔶';
      default:
        return '🛡️';
    }
  }

  // ── Map Section ─────────────────────────────────────────────────────────────

  Widget _buildMapSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionLabel('SAFETY OVERVIEW'),
        const SizedBox(height: 10),
        GestureDetector(
          onTap: widget.onOpenMapTab,
          child: Container(
            height: 180,
            decoration: BoxDecoration(
              color: AppColors.surface2,
              border: Border.all(
                  color: AppColors.accent.withValues(alpha: 0.2)),
              borderRadius: BorderRadius.circular(18),
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
                        color: AppColors.accent, strokeWidth: 2),
                  ),
                Positioned(
                  bottom: 10,
                  left: 12,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 9, vertical: 4),
                    decoration: BoxDecoration(
                      color: AppColors.bg.withValues(alpha: 0.88),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      _userVillage != null
                          ? '📍 ${_userVillage!.village}, ${_userVillage!.sector}'
                          : '📍 Musanze District · ${_mapData?.sectors.length ?? 0} sectors',
                      style: const TextStyle(
                          fontSize: 10,
                          color: AppColors.muted,
                          fontFamily: 'monospace'),
                    ),
                  ),
                ),
                Positioned(
                  top: 10,
                  right: 10,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(
                      color: AppColors.accent.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                          color: AppColors.accent.withValues(alpha: 0.4)),
                    ),
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.open_in_full_rounded,
                            size: 10, color: AppColors.accent),
                        SizedBox(width: 4),
                        Text(
                          'Expand Map',
                          style: TextStyle(
                              fontSize: 10, color: AppColors.accent),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  // ── Recent Reports ──────────────────────────────────────────────────────────

  Widget _buildRecentSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionLabel('RECENT REPORTS'),
        const SizedBox(height: 10),
        if (_loading)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 40),
            child: Center(
                child: CircularProgressIndicator(color: AppColors.accent)),
          )
        else if (_recentReports.isEmpty)
          _buildEmptyState()
        else
          ..._recentReports.map(_buildReportItem),
      ],
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
      padding: const EdgeInsets.symmetric(vertical: 36),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: AppColors.surface2.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: AppColors.accent.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Icon(Icons.shield_outlined,
                size: 28, color: AppColors.accent),
          ),
          const SizedBox(height: 14),
          const Text('No reports yet',
              style: TextStyle(
                  color: AppColors.text,
                  fontSize: 15,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          const Text('Tap + below to submit your first report',
              style: TextStyle(color: AppColors.muted, fontSize: 11)),
        ],
      ),
    );
  }
}

// ── Sub-widgets ───────────────────────────────────────────────────────────────

class _SectionLabel extends StatelessWidget {
  final String text;
  const _SectionLabel(this.text);

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 11,
        fontWeight: FontWeight.w700,
        color: AppColors.muted,
        letterSpacing: 0.9,
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String value;
  final String label;
  final IconData icon;
  final Color color;

  const _StatCard({
    required this.value,
    required this.label,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 12),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            color.withValues(alpha: 0.12),
            AppColors.surface2.withValues(alpha: 0.9),
          ],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(height: 8),
          Text(
            value,
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
              color: color,
              fontFamily: 'monospace',
            ),
          ),
          const SizedBox(height: 2),
          Text(
            label,
            style: const TextStyle(fontSize: 10, color: AppColors.muted),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}

class _SafeCard extends StatelessWidget {
  final double radiusKm;
  const _SafeCard({required this.radiusKm});

  @override
  Widget build(BuildContext context) {
    final label = radiusKm < 1.0
        ? '${(radiusKm * 1000).toInt()}m'
        : '${radiusKm.toStringAsFixed(radiusKm == radiusKm.toInt() ? 0 : 1)}km';
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            AppColors.ok.withValues(alpha: 0.10),
            AppColors.surface2.withValues(alpha: 0.85),
          ],
        ),
        border:
            Border.all(color: AppColors.ok.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        children: [
          Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
              color: AppColors.ok.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(13),
            ),
            child: const Icon(Icons.verified_user_rounded,
                color: AppColors.ok, size: 22),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'AREA CLEAR',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    color: AppColors.ok,
                    letterSpacing: 0.6,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  'No active hotspots within $label of your location. Stay alert and report any suspicious activity.',
                  style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.muted,
                      height: 1.45),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _NoLocationCard extends StatelessWidget {
  final VoidCallback? onOpenMap;
  const _NoLocationCard({this.onOpenMap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onOpenMap,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface2,
          border: Border.all(
              color: AppColors.accent2.withValues(alpha: 0.3)),
          borderRadius: BorderRadius.circular(18),
        ),
        child: const Row(
          children: [
            Icon(Icons.location_off_outlined,
                color: AppColors.accent2, size: 22),
            SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Location needed',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.text,
                    ),
                  ),
                  SizedBox(height: 3),
                  Text(
                    'Enable location to see nearby safety alerts and hotspot recommendations.',
                    style: TextStyle(
                        fontSize: 11,
                        color: AppColors.muted,
                        height: 1.4),
                  ),
                ],
              ),
            ),
            Icon(Icons.arrow_forward_ios_rounded,
                size: 13, color: AppColors.muted),
          ],
        ),
      ),
    );
  }
}
