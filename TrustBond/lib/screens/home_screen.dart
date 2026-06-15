import 'dart:math';
import 'package:flutter/material.dart';
import 'dart:async';
import 'package:geolocator/geolocator.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../widgets/musanze_map_painter.dart';
import '../models/musanze_map_data.dart';
import '../services/api_service.dart';
import '../services/device_service.dart';
import '../services/location_service.dart';
import '../services/hotspot_service.dart';
import '../services/hotspot_prefs_service.dart';
import '../services/app_refresh_bus.dart';
import '../services/notification_service.dart';
import '../services/proximity_alert_service.dart';
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
      return AppColors.danger;
    case 'active':
    case 'high':
      return AppColors.warn;
    case 'emerging':
    case 'medium':
      return AppColors.warn;
    case 'low_activity':
    case 'low':
      return AppColors.ok;
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
  StreamSubscription<int>? _unreadSub;
  StreamSubscription<Position>? _positionSub;
  int _unreadCount = 0;

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

  // Safety / Nearby — reads from shared singleton, always in sync with Map tab.
  double get _selectedRadiusKm => HotspotPrefsService.instance.radiusKm;
  int get _selectedTimeHours => HotspotPrefsService.instance.timeWindowHours;
  List<Hotspot> _nearbyHotspots = [];
  bool _loadingHotspots = false;

  static String _timeWindowLabel(int hours) => HotspotPrefsService.label(hours);

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
    _unreadCount = NotificationService().unreadCount;
    _unreadSub = NotificationService().unreadCountStream.listen((count) {
      if (mounted) setState(() => _unreadCount = count);
    });
    HotspotPrefsService.instance.addListener(_onHotspotPrefsChanged);

    // Listen to real-time position changes from the background proximity service
    _positionSub = ProximityAlertService().positionStream.listen((pos) {
      if (!mounted) return;
      final moved = _userLat == null ||
          _haversineKm(_userLat!, _userLng!, pos.latitude, pos.longitude) > 0.05;
      setState(() {
        _userLat = pos.latitude;
        _userLng = pos.longitude;
      });
      // Only reload hotspots if the user moved more than ~50m
      if (moved) _loadAllHotspots();
    });
  }

  @override
  void dispose() {
    HotspotPrefsService.instance.removeListener(_onHotspotPrefsChanged);
    _pulseController.dispose();
    _refreshSub?.cancel();
    _unreadSub?.cancel();
    _positionSub?.cancel();
    super.dispose();
  }

  /// Called whenever the shared time window changes (e.g. user changed it on the Map tab).
  void _onHotspotPrefsChanged() {
    if (!mounted) return;
    setState(() {}); // rebuild header label
    _loadAllHotspots();
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
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                  'Device registration failed. Please check your internet connection and restart the app.'),
              duration: Duration(seconds: 5),
            ),
          );
        }
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
      final hotspots = await _hotspotService.getAllHotspots(
        timeWindowHours: _selectedTimeHours,
      );
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
    setState(() => _loadingHotspots = true);
    // Write to shared singleton — both Home and Map tabs will react via their listeners.
    HotspotPrefsService.instance.setRadiusKm(km);
    try {
      final all = await _hotspotService.getAllHotspots(timeWindowHours: _selectedTimeHours);
      _updateNearbyHotspots(all);
    } catch (_) {}
    if (mounted) setState(() => _loadingHotspots = false);
  }

  Future<void> _onTimeWindowChanged(int hours) async {
    // Write to shared singleton — both Home and Map tabs will react via their listeners.
    HotspotPrefsService.instance.setTimeWindow(hours);
    // Listener (_onHotspotPrefsChanged) handles the reload; nothing else needed here.
  }

  Future<void> _pickTimeWindow() async {
    final controller = TextEditingController();
    String selectedUnit = 'Days';
    const units = ['Hours', 'Days', 'Months', 'Years'];

    final result = await showDialog<int>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: AppColors.surface,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          title: const Text(
            'Set Time Window',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Show safety recommendations for incidents reported in the last:',
                style: TextStyle(fontSize: 12, color: AppColors.muted, height: 1.5),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    flex: 2,
                    child: TextField(
                      controller: controller,
                      keyboardType: TextInputType.number,
                      autofocus: true,
                      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                      decoration: InputDecoration(
                        hintText: '1',
                        hintStyle: TextStyle(color: AppColors.muted.withValues(alpha: 0.5)),
                        filled: true,
                        fillColor: AppColors.surface2,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: AppColors.border),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: AppColors.border),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: const BorderSide(color: AppColors.accent, width: 1.5),
                        ),
                        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    flex: 3,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      decoration: BoxDecoration(
                        color: AppColors.surface2,
                        border: Border.all(color: AppColors.border),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          value: selectedUnit,
                          dropdownColor: AppColors.surface,
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: AppColors.text,
                          ),
                          items: units.map((u) => DropdownMenuItem(value: u, child: Text(u))).toList(),
                          onChanged: (v) {
                            if (v != null) setLocal(() => selectedUnit = v);
                          },
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              // Quick pick chips
              Wrap(
                spacing: 7,
                runSpacing: 6,
                children: [
                  _quickChip('24h', 24, controller, setLocal, () => selectedUnit = 'Hours'),
                  _quickChip('3 days', 72, controller, setLocal, () => selectedUnit = 'Hours'),
                  _quickChip('1 week', 7, controller, setLocal, () => selectedUnit = 'Days'),
                  _quickChip('1 month', 1, controller, setLocal, () => selectedUnit = 'Months'),
                  _quickChip('3 months', 3, controller, setLocal, () => selectedUnit = 'Months'),
                  _quickChip('1 year', 1, controller, setLocal, () => selectedUnit = 'Years'),
                ],
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('Cancel', style: TextStyle(color: AppColors.muted)),
            ),
            TextButton(
              onPressed: () {
                final n = int.tryParse(controller.text.trim()) ?? 0;
                if (n <= 0) return;
                final hours = switch (selectedUnit) {
                  'Hours'  => n,
                  'Days'   => n * 24,
                  'Months' => n * 30 * 24,
                  'Years'  => n * 365 * 24,
                  _        => n * 24,
                };
                // Cap at 2 years
                Navigator.of(ctx).pop(hours.clamp(1, 17520));
              },
              child: const Text('Apply', style: TextStyle(color: AppColors.accent, fontWeight: FontWeight.w700)),
            ),
          ],
        ),
      ),
    );

    if (result != null) _onTimeWindowChanged(result);
  }

  Widget _quickChip(String label, num value, TextEditingController ctrl,
      StateSetter setLocal, VoidCallback setUnit) {
    return GestureDetector(
      onTap: () => setLocal(() {
        ctrl.text = '$value';
        setUnit();
      }),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: AppColors.accent.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppColors.accent.withValues(alpha: 0.3)),
        ),
        child: Text(label,
            style: const TextStyle(
                fontSize: 11, fontWeight: FontWeight.w600, color: AppColors.accent)),
      ),
    );
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
                padding: const EdgeInsets.symmetric(horizontal: 16),
                sliver: SliverList(
                  delegate: SliverChildListDelegate([
                    _buildTrustScoreCard(),
                    const SizedBox(height: 6),
                    _buildSafetyTicker(),
                    const SizedBox(height: 6),
                    _buildSafetyAlertSection(),
                    const SizedBox(height: 10),
                    _buildMapSection(),
                    const SizedBox(height: 10),
                    _buildRecentSection(),
                    const SizedBox(height: 16),
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
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
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
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: Image.asset(
              'assets/images/logo.jpeg',
              width: 32,
              height: 32,
              fit: BoxFit.cover,
            ),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _userVillage != null
                      ? '${_userVillage!.village}, ${_userVillage!.cell}'
                      : 'Musanze District',
                  style: const TextStyle(
                      fontSize: 9, color: AppColors.muted),
                ),
                const Text(
                  'TrustBond Safety',
                  style: TextStyle(
                    fontSize: 15,
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
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: AppColors.surface2,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.border),
                  ),
                  child: const Icon(Icons.notifications_outlined,
                      size: 17, color: AppColors.text),
                ),
                if (_unreadCount > 0)
                  Positioned(
                    top: 6,
                    right: 6,
                    child: Container(
                      width: 7,
                      height: 7,
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
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      margin: const EdgeInsets.only(bottom: 2),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppColors.accent.withValues(alpha: 0.10),
            AppColors.surface2.withValues(alpha: 0.9),
          ],
        ),
        border: Border.all(color: AppColors.accent.withValues(alpha: 0.25)),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          TrustScoreRing(score: _trustScore, color: scoreColor, size: 40),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'TRUST SCORE',
                  style: TextStyle(
                      fontSize: 8,
                      color: AppColors.muted,
                      letterSpacing: 1.0),
                ),
                const SizedBox(height: 2),
                Text(
                  _trustScore >= 70
                      ? 'Good Standing'
                      : _trustScore >= 40
                          ? 'Moderate'
                          : 'Needs Improvement',
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: AppColors.accent,
                  ),
                ),
                Text(
                  '${_trustScore.toStringAsFixed(1)} / 100 · $_totalReports reports · $_verifiedReports verified',
                  style: const TextStyle(
                      fontSize: 9, color: AppColors.muted),
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
            color: AppColors.accent,
            size: 18,
          ),
        ],
      ),
    );
  }

  // ── Stats Grid ──────────────────────────────────────────────────────────────

  // ── Safety Alert Section ────────────────────────────────────────────────────

  Widget _buildSafetyAlertSection() {
    final timeLabel = _timeWindowLabel(_selectedTimeHours);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.location_on_rounded,
                size: 13, color: AppColors.accent),
            const SizedBox(width: 5),
            const Text(
              'SAFETY NEAR YOU',
              style: TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w700,
                color: AppColors.muted,
                letterSpacing: 0.9,
              ),
            ),
            const Spacer(),
            if (_loadingHotspots)
              const SizedBox(
                width: 10,
                height: 10,
                child: CircularProgressIndicator(
                    strokeWidth: 1.5, color: AppColors.accent),
              )
            else ...[
              _buildDistanceSelector(),
              const SizedBox(width: 6),
              GestureDetector(
                onTap: _pickTimeWindow,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(
                    color: AppColors.accent.withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: AppColors.accent.withValues(alpha: 0.35)),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.schedule_rounded, size: 12, color: AppColors.accent),
                      const SizedBox(width: 4),
                      Text(
                        timeLabel,
                        style: const TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w700,
                          color: AppColors.accent,
                        ),
                      ),
                      const SizedBox(width: 3),
                      const Icon(Icons.expand_more_rounded, size: 12, color: AppColors.accent),
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
        const SizedBox(height: 6),
        _buildAlertCard(),
      ],
    );
  }

  String _radiusLabel(double km) => HotspotPrefsService.radiusLabel(km);

  Future<void> _pickRadius() async {
    final controller = TextEditingController();
    String selectedUnit = 'km';
    const units = ['m', 'km'];

    final result = await showDialog<double>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: AppColors.surface,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          title: const Text(
            'Set Alert Radius',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Show safety alerts for hotspots within:',
                style: TextStyle(fontSize: 12, color: AppColors.muted, height: 1.5),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    flex: 2,
                    child: TextField(
                      controller: controller,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      autofocus: true,
                      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                      decoration: InputDecoration(
                        hintText: '1.5',
                        hintStyle: TextStyle(color: AppColors.muted.withValues(alpha: 0.5)),
                        filled: true,
                        fillColor: AppColors.surface2,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: AppColors.border),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: AppColors.border),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: const BorderSide(color: AppColors.accent, width: 1.5),
                        ),
                        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    flex: 2,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      decoration: BoxDecoration(
                        color: AppColors.surface2,
                        border: Border.all(color: AppColors.border),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          value: selectedUnit,
                          dropdownColor: AppColors.surface,
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: AppColors.text,
                          ),
                          items: units.map((u) => DropdownMenuItem(value: u, child: Text(u))).toList(),
                          onChanged: (v) {
                            if (v != null) setLocal(() => selectedUnit = v);
                          },
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 7,
                runSpacing: 6,
                children: [
                  _quickChip('500m', 500, controller, setLocal, () => selectedUnit = 'm'),
                  _quickChip('1km', 1, controller, setLocal, () => selectedUnit = 'km'),
                  _quickChip('1.5km', 1.5, controller, setLocal, () => selectedUnit = 'km'),
                  _quickChip('3km', 3, controller, setLocal, () => selectedUnit = 'km'),
                  _quickChip('5km', 5, controller, setLocal, () => selectedUnit = 'km'),
                  _quickChip('10km', 10, controller, setLocal, () => selectedUnit = 'km'),
                ],
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('Cancel', style: TextStyle(color: AppColors.muted)),
            ),
            TextButton(
              onPressed: () {
                final n = double.tryParse(controller.text.trim()) ?? 0;
                if (n <= 0) return;
                final km = selectedUnit == 'm' ? n / 1000.0 : n;
                Navigator.of(ctx).pop(km.clamp(0.1, 50.0));
              },
              child: const Text('Apply', style: TextStyle(color: AppColors.accent, fontWeight: FontWeight.w700)),
            ),
          ],
        ),
      ),
    );

    if (result != null) _onRadiusChanged(result);
  }

  Widget _buildDistanceSelector() {
    return GestureDetector(
      onTap: _pickRadius,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: AppColors.accent.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.accent.withValues(alpha: 0.35)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.radar_rounded, size: 12, color: AppColors.accent),
            const SizedBox(width: 5),
            Text(
              _radiusLabel(_selectedRadiusKm),
              style: const TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w700,
                color: AppColors.accent,
              ),
            ),
            const SizedBox(width: 4),
            const Icon(Icons.expand_more_rounded, size: 12, color: AppColors.accent),
          ],
        ),
      ),
    );
  }

  Widget _buildAlertCard() {
    if (_userLat == null || _userLng == null) {
      return _NoLocationCard(onOpenMap: widget.onOpenMapTab);
    }

    if (_nearbyHotspots.isEmpty) {
      return _SafeCard(radiusKm: _selectedRadiusKm);
    }

    // Show up to 3 alerts inline
    final shown = _nearbyHotspots.take(3).toList();

    return Column(
      children: [
        ...shown.map((h) {
          final dist = _haversineKm(_userLat!, _userLng!, h.centerLat, h.centerLong);
          final riskColor = _riskColor(h.riskLevel);
          final distLabel = dist < 1.0 ? '${(dist * 1000).toInt()}m' : '${dist.toStringAsFixed(1)}km';
          return Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            margin: const EdgeInsets.only(bottom: 6),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [AppColors.accent.withValues(alpha: 0.08), AppColors.surface2.withValues(alpha: 0.85)],
              ),
              border: Border.all(color: AppColors.accent.withValues(alpha: 0.25)),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                Icon(_riskIcon(h.riskLevel), size: 16, color: riskColor),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text.rich(
                        TextSpan(children: [
                          TextSpan(
                            text: _riskLabel(h.riskLevel),
                            style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: riskColor),
                          ),
                          TextSpan(
                            text: ' · $distLabel away${h.areaLabel != null && h.areaLabel!.isNotEmpty ? ' · ${h.areaLabel}' : ''}',
                            style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: AppColors.accent),
                          ),
                        ]),
                      ),
                      Text(
                        '${h.incidentTypeName ?? 'Incident'} · ${h.incidentCount} reports',
                        style: const TextStyle(fontSize: 9, color: AppColors.muted),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        }),
        if (_nearbyHotspots.length > 3)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text(
              '+${_nearbyHotspots.length - 3} more alert${_nearbyHotspots.length > 4 ? 's' : ''} nearby',
              style: TextStyle(fontSize: 9, color: AppColors.accent.withValues(alpha: 0.7)),
            ),
          ),
        const SizedBox(height: 2),
        Row(
          children: [
            Expanded(
              child: GestureDetector(
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const ReportStep1Screen()),
                ),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 7),
                  decoration: BoxDecoration(
                    color: AppColors.accent,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  alignment: Alignment.center,
                  child: const Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.report_rounded, size: 12, color: AppColors.onAccent),
                      SizedBox(width: 5),
                      Text('Report Incident', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: AppColors.onAccent)),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: GestureDetector(
                onTap: widget.onOpenMapTab,
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 7),
                  decoration: BoxDecoration(
                    color: AppColors.accent.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.accent.withValues(alpha: 0.4)),
                  ),
                  alignment: Alignment.center,
                  child: const Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.map_rounded, size: 12, color: AppColors.accent),
                      SizedBox(width: 5),
                      Text(
                        'View All Alerts',
                        style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: AppColors.accent),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  // ── Safety Tips ─────────────────────────────────────────────────────────────

  static const _fallbackTips = [
    (Icons.notifications_outlined, 'Stay Alert', 'Keep aware of your surroundings at all times.'),
    (Icons.smartphone_outlined, 'Report Fast', 'Report incidents quickly — early reports save lives.'),
    (Icons.group_outlined, 'Travel Together', 'Move in groups especially at night or in risky areas.'),
    (Icons.location_on_outlined, 'Share Location', 'Let trusted contacts know where you are.'),
  ];

  /// Build a single combined recommendation covering all nearby risk areas,
  /// including exact distance and area/village names per hotspot.
  String _buildCombinedRecommendation() {
    if (_nearbyHotspots.isEmpty) {
      return 'Your area is currently safe. Stay alert and report any suspicious activity to help keep Musanze safe.';
    }

    if (_userLat == null || _userLng == null) {
      return 'Enable location to receive personalised safety recommendations.';
    }

    // Build per-hotspot fragments like "200m away in Mpenge there is an increase in assault"
    final fragments = <String>[];
    for (final h in _nearbyHotspots) {
      final distKm = _haversineKm(_userLat!, _userLng!, h.centerLat, h.centerLong);
      final distLabel = distKm < 1.0
          ? '${(distKm * 1000).toInt()}m'
          : '${distKm.toStringAsFixed(1)}km';
      final area = h.areaLabel ?? '';
      final crime = h.incidentTypeName ?? 'incident';
      final areaStr = area.isNotEmpty ? ' in $area' : '';
      fragments.add('$distLabel away$areaStr there is ${_riskVerb(h.riskLevel)} $crime activity');
      if (fragments.length >= 4) break; // keep ticker readable
    }

    final intro = 'Stay alert: ';
    final tail = '. Report any suspicious activity.';
    return '$intro${fragments.join('; ')}$tail';
  }

  /// Verb phrase matching risk severity for recommendation text.
  String _riskVerb(String riskLevel) {
    switch (riskLevel.toLowerCase()) {
      case 'critical':
        return 'critical';
      case 'active':
      case 'high':
        return 'high';
      case 'emerging':
      case 'medium':
        return 'emerging';
      default:
        return 'some';
    }
  }

  /// Detailed per-hotspot tips for the bottom sheet, with distance and area.
  List<(IconData, String, String)> _buildDetailedTips() {
    final liveTips = <(IconData, String, String)>[];
    for (final h in _nearbyHotspots) {
      // Distance label
      String distLabel = '';
      if (_userLat != null && _userLng != null) {
        final d = _haversineKm(_userLat!, _userLng!, h.centerLat, h.centerLong);
        distLabel = d < 1.0 ? '${(d * 1000).toInt()}m' : '${d.toStringAsFixed(1)}km';
      }
      final area = h.areaLabel ?? '';
      final locationTag = [
        if (distLabel.isNotEmpty) distLabel,
        if (area.isNotEmpty) area,
      ].join(' · ');
      final title = '${h.incidentTypeName ?? 'Alert'} · ${h.incidentCount} reports${locationTag.isNotEmpty ? ' · $locationTag' : ''}';

      final advisory = h.citizenAdvisory?.trim() ?? '';
      if (advisory.isNotEmpty) {
        final text = advisory.length > 120 ? '${advisory.substring(0, 120)}...' : advisory;
        liveTips.add((_riskIcon(h.riskLevel), title, text));
      } else {
        liveTips.add((_riskIcon(h.riskLevel), title,
            _safetyMessage(h.riskLevel, h.incidentTypeName)));
      }
      if (liveTips.length >= 6) break;
    }
    return liveTips.isNotEmpty ? liveTips : _fallbackTips;
  }

  void _showRecommendationsSheet() {
    final tips = _buildDetailedTips();
    final combined = _buildCombinedRecommendation();
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        minChildSize: 0.3,
        maxChildSize: 0.85,
        expand: false,
        builder: (ctx, scrollCtrl) => Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          child: ListView(
            controller: scrollCtrl,
            children: [
              Center(
                child: Container(
                  width: 36, height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.muted.withValues(alpha: 0.3),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  const Icon(Icons.shield_outlined, size: 16, color: AppColors.accent),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Safety Recommendations · ${_timeWindowLabel(_selectedTimeHours)}',
                      style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.text),
                    ),
                  ),
                  GestureDetector(
                    onTap: () { Navigator.pop(ctx); _pickTimeWindow(); },
                    child: const Icon(Icons.tune_rounded, size: 18, color: AppColors.accent),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              // Combined summary
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AppColors.accent.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.accent.withValues(alpha: 0.2)),
                ),
                child: Text(
                  combined,
                  style: const TextStyle(fontSize: 12, color: AppColors.text, height: 1.5),
                ),
              ),
              if (tips.length > 1) ...[
                const SizedBox(height: 16),
                const Text(
                  'DETAILS BY AREA',
                  style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: AppColors.muted, letterSpacing: 0.9),
                ),
                const SizedBox(height: 8),
              ],
              ...tips.map((tip) {
                final (icon, title, desc) = tip;
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(icon, size: 16, color: AppColors.accent),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(title, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.text)),
                            const SizedBox(height: 2),
                            Text(desc, style: const TextStyle(fontSize: 11, color: AppColors.muted, height: 1.4)),
                          ],
                        ),
                      ),
                    ],
                  ),
                );
              }),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSafetyTicker() {
    final tickerText = _buildCombinedRecommendation();

    return GestureDetector(
      onTap: _showRecommendationsSheet,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: AppColors.accent.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AppColors.accent.withValues(alpha: 0.2)),
        ),
        child: Row(
          children: [
            const Icon(Icons.shield_outlined, size: 12, color: AppColors.accent),
            const SizedBox(width: 6),
            Expanded(
              child: SizedBox(
                height: 16,
                child: _MarqueeText(text: tickerText),
              ),
            ),
            const SizedBox(width: 6),
            const Icon(Icons.arrow_forward_ios_rounded, size: 10, color: AppColors.accent),
          ],
        ),
      ),
    );
  }

  IconData _riskIcon(String riskLevel) {
    switch (riskLevel.toLowerCase()) {
      case 'critical':
        return Icons.crisis_alert;
      case 'high':
      case 'active':
        return Icons.warning_amber_rounded;
      case 'medium':
      case 'emerging':
        return Icons.info_outline;
      default:
        return Icons.shield_outlined;
    }
  }

  // ── Map Section ─────────────────────────────────────────────────────────────

  Widget _buildMapSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionLabel('SAFETY OVERVIEW'),
        const SizedBox(height: 6),
        GestureDetector(
          onTap: widget.onOpenMapTab,
          child: Container(
            height: 130,
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
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.location_on_outlined, size: 11, color: AppColors.muted),
                        const SizedBox(width: 3),
                        Text(
                          _userVillage != null
                              ? '${_userVillage!.village}, ${_userVillage!.sector}'
                              : 'Musanze District · ${_mapData?.sectors.length ?? 0} sectors',
                          style: const TextStyle(
                              fontSize: 10,
                              color: AppColors.muted,
                              fontFamily: 'monospace'),
                        ),
                      ],
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
        const SizedBox(height: 6),
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
      padding: const EdgeInsets.symmetric(vertical: 20),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: AppColors.surface2.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: AppColors.accent.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Icon(Icons.shield_outlined,
                size: 20, color: AppColors.accent),
          ),
          const SizedBox(height: 8),
          const Text('No reports yet',
              style: TextStyle(
                  color: AppColors.text,
                  fontSize: 13,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 2),
          const Text('Tap + below to submit your first report',
              style: TextStyle(color: AppColors.muted, fontSize: 10)),
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
        fontSize: 9,
        fontWeight: FontWeight.w700,
        color: AppColors.muted,
        letterSpacing: 0.9,
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
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            AppColors.accent.withValues(alpha: 0.08),
            AppColors.surface2.withValues(alpha: 0.85),
          ],
        ),
        border:
            Border.all(color: AppColors.accent.withValues(alpha: 0.25)),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: AppColors.ok.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Icon(Icons.verified_user_rounded,
                color: AppColors.ok, size: 18),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'AREA CLEAR',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w800,
                    color: AppColors.ok,
                    letterSpacing: 0.6,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  'No active hotspots within $label. Stay alert and report any suspicious activity.',
                  style: const TextStyle(
                      fontSize: 9,
                      color: AppColors.muted,
                      height: 1.4),
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
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: AppColors.surface2,
          border: Border.all(
              color: AppColors.accent.withValues(alpha: 0.25)),
          borderRadius: BorderRadius.circular(14),
        ),
        child: const Row(
          children: [
            Icon(Icons.location_off_outlined,
                color: AppColors.accent, size: 18),
            SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Location needed',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: AppColors.text,
                    ),
                  ),
                  SizedBox(height: 2),
                  Text(
                    'Enable location to see nearby safety alerts.',
                    style: TextStyle(
                        fontSize: 9,
                        color: AppColors.muted,
                        height: 1.3),
                  ),
                ],
              ),
            ),
            Icon(Icons.arrow_forward_ios_rounded,
                size: 11, color: AppColors.muted),
          ],
        ),
      ),
    );
  }
}

class _MarqueeText extends StatefulWidget {
  final String text;
  const _MarqueeText({required this.text});

  @override
  State<_MarqueeText> createState() => _MarqueeTextState();
}

class _MarqueeTextState extends State<_MarqueeText>
    with SingleTickerProviderStateMixin {
  late final ScrollController _scrollController;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _scrollController = ScrollController();
    WidgetsBinding.instance.addPostFrameCallback((_) => _startScroll());
  }

  void _startScroll() {
    if (!mounted || !_scrollController.hasClients) return;
    final maxExtent = _scrollController.position.maxScrollExtent;
    if (maxExtent <= 0) return;
    final duration = Duration(milliseconds: (maxExtent * 40).toInt());
    _scrollController.animateTo(
      maxExtent,
      duration: duration,
      curve: Curves.linear,
    ).then((_) {
      if (!mounted) return;
      _timer = Timer(const Duration(seconds: 1), () {
        if (!mounted || !_scrollController.hasClients) return;
        _scrollController.jumpTo(0);
        _startScroll();
      });
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      controller: _scrollController,
      scrollDirection: Axis.horizontal,
      physics: const NeverScrollableScrollPhysics(),
      child: Text(
        widget.text,
        style: const TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w600,
          color: AppColors.accent,
        ),
        maxLines: 1,
      ),
    );
  }
}
