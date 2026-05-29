// ignore_for_file: unused_field, unused_element, unnecessary_underscores, sized_box_for_whitespace

import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'dart:ui' as ui;
import '../config/theme.dart';
import '../models/musanze_map_data.dart';
import '../services/location_service.dart';
import '../services/api_service.dart';
import '../services/hotspot_service.dart';
import '../services/proximity_alert_service.dart';
import '../widgets/musanze_map_painter.dart' show sectorColor;

class SafetyMapScreen extends StatefulWidget {
  final bool showDetailedView;
  final String? initialSectorId;
  
  const SafetyMapScreen({
    super.key, 
    this.showDetailedView = false,
    this.initialSectorId,
  });

  @override
  State<SafetyMapScreen> createState() => _SafetyMapScreenState();
}

class _SafetyMapScreenState extends State<SafetyMapScreen> {
  MusanzeMapData? _mapData;
  String? _selectedSector;
  int? _selectedSectorId;
  int? _selectedCellId;
  String? _selectedCellName;
  String? _selectedVillageName;
  bool _loading = true;
  String? _error;

  // Detail level management
  bool _showDetailedView = false;
  String _currentDetailLevel = 'sector'; // Citizen map uses sector-level only.

  // GPS location state
  final _locationService = LocationService();
  final _api = ApiService();
  final _hotspotService = HotspotService();
  double? _userLat;
  double? _userLng;
  VillageLocation? _userVillage;
  /// Shown when GPS is known but [\_userVillage] is null (e.g. Kigali — outside Musanze polygons).
  String? _userLocationCaption;
  bool _locatingUser = false;
  bool _loadingHotspots = false;
  List<Hotspot> _hotspots = [];
  List<Map<String, dynamic>> _publicAlerts = [];
  bool _loadingAlerts = false;
  /// Default list/stats filter (1 week). Map always shows all clusters.
  int _hotspotTimeWindowHours = 168;
  int _nearbyHotspotRadiusMeters = 1500;
  final TextEditingController _distanceController =
      TextEditingController(text: '1.5');
  bool _distanceInKm = true;
  static const _distanceCalc = Distance();

  Timer? _hotspotRefreshTimer;

  final MapController _mapController = MapController();

  // Musanze District center
  static const _musanzeCenter = LatLng(-1.4975, 29.6347);
  static const double _initialZoom = 13.0;

  // Backend hierarchy lists
  List<Map<String, dynamic>> _sectors = [];
  List<Map<String, dynamic>> _cells = [];
  List<Map<String, dynamic>> _villages = [];
  bool _loadingHierarchy = false;

  // Adjacency-based colors (graph coloring)
  Map<String, Color> _sectorColors = {};
  Map<String, Color> _cellColors = {};
  Map<String, Color> _villageColors = {};

  @override
  void initState() {
    super.initState();
    _showDetailedView = widget.showDetailedView;
    _loadSavedRadius();
    _loadMap();
    _loadSectorsFromBackend();
    _getUserLocation();

    // Keep hotspots fresh (mobile app has no websocket push).
    _hotspotRefreshTimer = Timer.periodic(const Duration(seconds: 45), (_) {
      if (!mounted) return;
      _loadHotspots();
      _loadPublicAlerts();
    });
    
    // If coming from home screen with detailed view, show all sectors initially
    if (_showDetailedView) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        // Add a small delay to ensure map controller is initialized
        Future.delayed(const Duration(milliseconds: 100), () {
          if (mounted) {
            try {
              _mapController.move(_musanzeCenter, 14.0);
              setState(() {
                _currentDetailLevel = 'sector'; // Start at sector level for detailed view
              });
            } catch (e) {
              debugPrint('Map controller not ready yet: $e');
            }
          }
        });
      });
    }
  }

  Future<void> _loadSectorsFromBackend() async {
    setState(() => _loadingHierarchy = true);
    try {
      final res = await _api.getPublicLocations(locationType: 'sector', limit: 1000);
      if (!mounted) return;
      debugPrint('Loaded ${res.length} sectors from backend');
      setState(() {
        _sectors = res.cast<Map<String, dynamic>>();
        _loadingHierarchy = false;
      });
    } catch (e) {
      debugPrint('Failed to load sectors: $e');
      if (!mounted) return;
      setState(() => _loadingHierarchy = false);
    }
  }

  Future<void> _loadCells(int sectorId) async {
    setState(() {
      _loadingHierarchy = true;
      _cells = [];
      _villages = [];
      _selectedCellId = null;
      _selectedCellName = null;
    });
    try {
      final res = await _api.getPublicLocations(locationType: 'cell', parentId: sectorId, limit: 2000);
      if (!mounted) return;
      setState(() {
        _cells = res.cast<Map<String, dynamic>>();
        _loadingHierarchy = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loadingHierarchy = false);
    }
  }

  Future<void> _loadVillages(int cellId) async {
    setState(() {
      _loadingHierarchy = true;
      _villages = [];
    });
    try {
      final res = await _api.getPublicLocations(locationType: 'village', parentId: cellId, limit: 2000);
      if (!mounted) return;
      setState(() {
        _villages = res.cast<Map<String, dynamic>>();
        _loadingHierarchy = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loadingHierarchy = false);
    }
  }

  void _moveToCentroid(Map<String, dynamic> loc, double zoom) {
    final lat = loc['centroid_lat'];
    final lng = loc['centroid_long'];
    if (lat is num && lng is num) {
      _mapController.move(LatLng(lat.toDouble(), lng.toDouble()), zoom);
    }
  }

  /// Polygon-only village match (no far-away "nearest village" guess).
  void _applyUserLocationFromGps(double lat, double lng) {
    final village = _mapData?.findVillage(lat, lng);
    final outside = village == null;
    setState(() {
      _userLat = lat;
      _userLng = lng;
      _userVillage = village;
      _userLocationCaption = outside
          ? '${lat.toStringAsFixed(5)}, ${lng.toStringAsFixed(5)}'
          : null;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _centerOnUser();
    });
  }

  double _distanceToHotspotMeters(Hotspot hotspot) {
    if (_userLat == null || _userLng == null) {
      return hotspot.distanceMeters ?? double.infinity;
    }
    return _distanceCalc(
      LatLng(_userLat!, _userLng!),
      LatLng(hotspot.centerLat, hotspot.centerLong),
    );
  }

  double get _alertsRadiusKm =>
      (_nearbyHotspotRadiusMeters / 1000.0).clamp(0.5, 3.0);

  Future<void> _loadSavedRadius() async {
    final meters = await ProximityAlertService.loadSavedRadius();
    if (!mounted) return;
    setState(() {
      _nearbyHotspotRadiusMeters = meters.toInt();
      _distanceController.text =
          _distanceInKm ? (meters / 1000).toStringAsFixed(1) : meters.toStringAsFixed(0);
    });
  }

  Future<void> _getUserLocation() async {
    setState(() => _locatingUser = true);
    try {
      final result = await _locationService.getFullLocation();
      if (result.hasPosition && mounted) {
        final lat = result.latitude!;
        final lng = result.longitude!;
        _applyUserLocationFromGps(lat, lng);
        setState(() => _locatingUser = false);
        _loadHotspots();
        _loadPublicAlerts();
      } else {
        if (mounted) setState(() => _locatingUser = false);
      }
    } catch (_) {
      if (mounted) setState(() => _locatingUser = false);
    }
  }

  Future<void> _loadMap() async {
    try {
      debugPrint('Starting to load map data...');
      MusanzeMapData data;
      try {
        final geo = await _api.getPublicLocationsGeoJson(locationType: 'village', limit: 10000);
        debugPrint('Loaded GeoJSON with ${geo.length} features');
        data = MusanzeMapData.parse(jsonEncode(geo));
        debugPrint('Parsed map data with ${data.sectors.length} sectors');
      } catch (e) {
        debugPrint('Failed to load GeoJSON, falling back to bundled data: $e');
        data = await MusanzeMapData.load();
        debugPrint('Loaded bundled map data with ${data.sectors.length} sectors');
      }
      if (mounted) {
      setState(() {
        _mapData = data;
          _sectorColors = data.sectorColorMap();
          _cellColors = {};
          _villageColors = {};
        _loading = false;
      });
        if (_userLat != null && _userLng != null) {
          _applyUserLocationFromGps(_userLat!, _userLng!);
          _loadHotspots();
          _loadPublicAlerts();
        }
        debugPrint('Map data loaded and state updated');
      }
    } catch (e) {
      debugPrint('Failed to load map: $e');
      if (mounted) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
      }
    }
  }

  Future<void> _loadHotspots() async {
    if (_loadingHotspots) return;
    if (_userLat == null || _userLng == null) {
      if (mounted) {
        setState(() {
          _hotspots = [];
          _loadingHotspots = false;
        });
      }
      return;
    }
    setState(() => _loadingHotspots = true);
    try {
      debugPrint(
        'Loading nearby clusters (${_nearbyHotspotRadiusMeters}m, '
        '${_hotspotTimeWindowHours}h)',
      );
      final hotspots = await _hotspotService.getNearbyHotspots(
        lat: _userLat!,
        lon: _userLng!,
        radiusMeters: _nearbyHotspotRadiusMeters,
        timeWindowHours: _hotspotTimeWindowHours,
      );
      debugPrint('Received ${hotspots.length} hotspots from service');

      final mapData = _mapData;
      final radius = _nearbyHotspotRadiusMeters.toDouble();
      var filtered = mapData == null
          ? hotspots
          : hotspots.where((h) {
              final village = mapData.findVillage(h.centerLat, h.centerLong);
              return village != null;
            }).toList();

      filtered = filtered
          .where((h) => _distanceToHotspotMeters(h) <= radius)
          .toList()
        ..sort(
          (a, b) =>
              _distanceToHotspotMeters(a).compareTo(_distanceToHotspotMeters(b)),
        );

      debugPrint('Filtered to ${filtered.length} hotspots near you');
      
      if (!mounted) return;
      setState(() {
        _hotspots = filtered;
        _loadingHotspots = false;
      });
    } catch (e) {
      debugPrint('Error loading hotspots: $e');
      if (!mounted) return;
      setState(() => _loadingHotspots = false);
    }
  }

  Future<void> _loadPublicAlerts() async {
    if (_loadingAlerts) return;
    if (_userLat == null || _userLng == null) {
      if (mounted) {
        setState(() {
          _publicAlerts = [];
        });
      }
      return;
    }

    setState(() => _loadingAlerts = true);
    try {
      final alerts = await _api.getPublicAlerts(
        latitude: _userLat!,
        longitude: _userLng!,
        radiusKm: _alertsRadiusKm,
        limit: 10,
      );
      if (!mounted) return;
      setState(() {
        _publicAlerts = alerts.cast<Map<String, dynamic>>();
        _loadingAlerts = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loadingAlerts = false;
      });
    }
  }

  @override
  void dispose() {
    _distanceController.dispose();
    _hotspotRefreshTimer?.cancel();
    super.dispose();
  }

  /// Build polygon layers from GeoJSON data.
  List<Polygon> _buildPolygons() {
    if (_mapData == null) return [];
    final polygons = <Polygon>[];

    final level = _currentDetailLevel;

    Iterable<MapFeature> feats = _mapData!.features;
    if (level == 'cell') {
      feats = feats.where((f) => f.sector == _selectedSector);
    } else if (level == 'village') {
      feats = feats.where((f) => f.sector == _selectedSector && f.cell == _selectedCellName);
    }

    for (final feature in feats) {
      Color baseColor;
      baseColor = _sectorColors[feature.sector] ?? sectorColor(feature.sector);

      for (final ring in feature.rings) {
        if (ring.length < 3) continue;
        final points = ring.map((pt) => LatLng(pt.dy, pt.dx)).toList();
        polygons.add(Polygon(
          points: points,
          color: baseColor.withValues(alpha: 0.1),
          // Match home screen stroke exactly
          borderColor: baseColor.withValues(alpha: 0.3),
          borderStrokeWidth: 0.4,
        ));
      }
    }
    return polygons;
  }

  /// Build label markers for current drill-down level.
  List<Marker> _buildRegionLabels() {
    if (_mapData == null) return [];
    final markers = <Marker>[];
    for (final sector in _mapData!.sectors) {
      final centroid = _mapData!.sectorCentroid(sector);
        if (centroid == ui.Offset.zero) continue;
        final color = _sectorColors[sector] ?? sectorColor(sector);
        markers.add(_nameMarker(LatLng(centroid.dy, centroid.dx), sector, color));
      }
      return markers;
  }

  Marker _nameMarker(LatLng point, String name, Color color) {
    return Marker(
      point: point,
      width: 130,
      height: 30,
      child: IgnorePointer(
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: AppColors.bg.withValues(alpha: 0.72),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.border.withValues(alpha: 0.6)),
            ),
            child: Text(
              name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w700,
                color: color,
              ),
              textAlign: TextAlign.center,
            ),
          ),
        ),
      ),
    );
  }

  /// Build user location marker.
  List<Marker> _buildUserMarker() {
    if (_userLat == null || _userLng == null) return [];
    return [
      Marker(
        point: LatLng(_userLat!, _userLng!),
        width: 36,
        height: 36,
        child: Stack(
          alignment: Alignment.center,
          children: [
            Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.accent.withValues(alpha: 0.15),
              ),
            ),
            Container(
              width: 20,
              height: 20,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.accent.withValues(alpha: 0.3),
              ),
            ),
            Container(
              width: 11,
              height: 11,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.accent,
                border: Border.all(color: Colors.white, width: 2),
              ),
            ),
          ],
        ),
      ),
    ];
  }

  bool _hotspotInSelectedFilter(Hotspot hotspot) {
    final cutoff =
        DateTime.now().subtract(Duration(hours: _hotspotTimeWindowHours));
    return hotspot.detectedAt.isAfter(cutoff);
  }

  List<Marker> _buildHotspotMarkers() {
    if (_hotspots.isEmpty) return [];
    return _hotspots.map((hotspot) {
      final color = _getHotspotColor(hotspot.riskLevel);
      final isSecurityCluster = hotspot.incidentCount >= 3; // Security clusters have 3+ incidents
      final inFilter = _hotspotInSelectedFilter(hotspot);
      final fade = inFilter ? 1.0 : 0.42;
      
      return Marker(
        point: LatLng(hotspot.centerLat, hotspot.centerLong),
        width: isSecurityCluster ? 45 : 38,
        height: isSecurityCluster ? 45 : 38,
        child: GestureDetector(
          onTap: () => _showHotspotDetails(hotspot),
          child: Opacity(
            opacity: fade,
            child: Stack(
            alignment: Alignment.center,
            children: [
              // Outer glow for security clusters
              if (isSecurityCluster)
                Container(
                  width: 35,
                  height: 35,
                  decoration: BoxDecoration(
                    color: Colors.red.withValues(alpha: fade * 0.2),
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.red.withValues(alpha: fade * 0.4), width: 1),
                  ),
                ),
              // Main hotspot circle
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: fade * 0.25),
                  shape: BoxShape.circle,
                ),
              ),
              // Inner circle
              Container(
                width: 16,
                height: 16,
                decoration: BoxDecoration(
                  color: isSecurityCluster ? Colors.red : color,
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.bg, width: 1.8),
                ),
              ),
              // Security cluster indicator
              if (isSecurityCluster)
                Positioned(
                  top: 0,
                  right: 0,
                  child: Container(
                    width: 12,
                    height: 12,
                    decoration: BoxDecoration(
                      color: Colors.red,
                      shape: BoxShape.circle,
                      border: Border.all(color: AppColors.bg, width: 1.5),
                    ),
                    child: const Icon(
                      Icons.warning,
                      size: 8,
                      color: Colors.white,
                    ),
                  ),
                ),
            ],
            ),
          ),
        ),
      );
    }).toList();
  }

  Color _getHotspotColor(String riskLevel) {
    switch (riskLevel.toLowerCase()) {
      case 'critical':
      case 'high':
      case 'active':
        return AppColors.danger;
      case 'warning':
      case 'medium':
      case 'emerging':
        return AppColors.warn;
      case 'normal':
      case 'low_activity':
      case 'low':
        return AppColors.ok;
      default:
        return AppColors.muted;
    }
  }

  String _formatHotspotWindow(int hours) {
    String unit(int amount, String name) =>
        '$amount $name${amount == 1 ? '' : 's'}';
    if (hours >= 8760) return unit((hours / 8760).round(), 'year');
    if (hours >= 720) return unit((hours / 720).round(), 'month');
    if (hours >= 24) return unit((hours / 24).round(), 'day');
    return unit(hours, 'hour');
  }

  void _showHotspotDetails(Hotspot hotspot) {
    final isSecurityCluster = hotspot.incidentCount >= 3;
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: Row(
          children: [
            if (isSecurityCluster) ...[
              const Icon(Icons.warning, color: Colors.red, size: 20),
              const SizedBox(width: 4),
              const Text('Security Cluster', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
            ] else ...[
              Text(hotspot.riskEmoji),
              const SizedBox(width: 8),
              Text(hotspot.riskText),
            ],
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (isSecurityCluster) ...[
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.red.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: Colors.red.withValues(alpha: 0.3)),
                ),
                child: const Text(
                  '⚠️ High-priority security area\nMultiple recent incidents detected',
                  style: TextStyle(fontSize: 12, color: Colors.red),
                ),
              ),
              const SizedBox(height: 8),
            ],
            if (_userLat != null && _userLng != null)
              Text(
                'Distance: ${(_distanceToHotspotMeters(hotspot) / 1000).toStringAsFixed(2)} km from you',
              ),
            Text('Incidents: ${hotspot.incidentCount}', 
                 style: TextStyle(fontWeight: isSecurityCluster ? FontWeight.bold : FontWeight.normal)),
            if (hotspot.incidentTypeName != null) 
              Text('Type: ${hotspot.incidentTypeName}'),
            Text('Time window: ${hotspot.timeWindowHours}h'),
            Text('Radius: ${hotspot.radiusMeters.toStringAsFixed(0)}m'),
            if (isSecurityCluster) ...[
              const SizedBox(height: 8),
              const Text(
                '📍 Stay alert in this area\n📱 Report any suspicious activity',
                style: TextStyle(fontSize: 11, color: AppColors.muted),
              ),
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  void _centerOnUser() {
    if (_userLat != null && _userLng != null) {
      _mapController.move(LatLng(_userLat!, _userLng!), 15.0);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildHeader(),
            _buildHotspotPeriodFilters(),
            _buildDistanceInput(),
            _buildLocationStatusStrip(),
            Expanded(
              flex: 3,
              child: _buildMap(),
            ),
            Container(
              height: 150,
              child: _buildSectorInfo(),
            ),
          ],
        ),
      ),
      // Only show bottom navigation when in detailed view (pushed route)
      bottomNavigationBar: widget.showDetailedView ? _buildBottomNavigationBar(context) : null,
    );
  }

  Widget _buildBottomNavigationBar(BuildContext context) {
    return Container(
      height: 60,
      decoration: const BoxDecoration(
        color: Color(0xF7080C18),
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: SafeArea(
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: [
            _navItem(context, 0, Icons.home_rounded, 'Home'),
            _navItem(context, 1, Icons.map_rounded, 'Map'),
            _navItem(context, 3, Icons.assignment_outlined, 'Reports'),
            _navItem(context, 4, Icons.person_outline_rounded, 'Profile'),
          ],
        ),
      ),
    );
  }

  Widget _navItem(BuildContext context, int index, IconData icon, String label) {
    final isSelected = index == 1; // Map is selected
    return GestureDetector(
      onTap: () {
        if (index == 1) {
          Navigator.of(context).pop(); // Go back to map tab
        } else {
          // Navigate to other tabs - for now just go back
          Navigator.of(context).pop();
        }
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(8),
          color: isSelected ? AppColors.accent.withValues(alpha: 0.15) : null,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 22, color: isSelected ? AppColors.accent : AppColors.text),
            const SizedBox(height: 2),
            Text(label,
                style: TextStyle(
                    fontSize: 11,
                    color: isSelected ? AppColors.accent : AppColors.text)),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
      child: Row(
        children: [
          const Text('Safety Map',
              style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700)),
          const Spacer(),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: AppColors.accent.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 6,
                  height: 6,
                  decoration: const BoxDecoration(
                    shape: BoxShape.circle,
                    color: AppColors.accent,
                  ),
                ),
                const SizedBox(width: 4),
                Text(
                  _loadingHotspots
                      ? 'Loading hotspots...'
                      : _mapData != null
                      ? '${_mapData!.features.length} villages · ${_hotspots.length} clusters · ${_formatHotspotWindow(_hotspotTimeWindowHours)} · ${_userLat != null && _userLng != null ? 'within ${(_nearbyHotspotRadiusMeters / 1000).toStringAsFixed(1)} km' : 'enable GPS'}'
                          : 'Loading...',
                  style: const TextStyle(
                      fontSize: 10,
                      color: AppColors.accent,
                      fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSectorFilters() {
    if (_mapData == null) return const SizedBox.shrink();
    
    // Use backend sectors if available, otherwise use map data sectors
    final sectorNames = _sectors.isNotEmpty
        ? _sectors
            .map((s) => (s['location_name'] ?? '').toString())
            .where((n) => n.isNotEmpty)
            .toList()
        : _mapData!.sectors;
    
    final sectors = ['All', ...sectorNames];
    debugPrint('Building sector filters with ${sectors.length} sectors');
    
    return Container(
      height: 34,
      margin: const EdgeInsets.symmetric(horizontal: 20),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: sectors.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, i) {
          final name = sectors[i];
          final sel =
              (i == 0 && _selectedSector == null) || name == _selectedSector;
          final color = i == 0
              ? AppColors.accent2
              : (_sectorColors[name] ?? sectorColor(name));
          return GestureDetector(
            onTap: () {
              final newSector = i == 0 ? null : name;
              int? sectorId;
              if (newSector != null && _sectors.isNotEmpty) {
                final match = _sectors.firstWhere(
                  (s) => (s['location_name'] ?? '').toString() == newSector,
                  orElse: () => const {},
                );
                final id = match['location_id'];
                if (id is int) sectorId = id;
              }
              setState(() {
                _selectedSector = newSector;
                _selectedSectorId = sectorId;
                _selectedCellId = null;
                _selectedCellName = null;
                _selectedVillageName = null;
                _cells = [];
                _villages = [];
                _currentDetailLevel = 'sector';
                _cellColors = {};
                _villageColors = {};
              });
              if (i > 0 && _mapData != null) {
                final centroid = _mapData!.sectorCentroid(name);
                _mapController.move(
                    LatLng(centroid.dy, centroid.dx), 14.5);
              } else {
                _mapController.move(_musanzeCenter, _initialZoom);
              }
            },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 150),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              decoration: BoxDecoration(
                color:
                    sel ? color.withValues(alpha: 0.15) : AppColors.surface2,
                border:
                    Border.all(color: sel ? color : AppColors.border),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(
                name,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: sel ? FontWeight.w600 : FontWeight.normal,
                  color: sel ? color : AppColors.muted,
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildHotspotPeriodFilters() {
    const periods = <int>[24, 168, 720, 2160, 8760];
    return Container(
      height: 34,
      margin: const EdgeInsets.fromLTRB(20, 8, 20, 0),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: periods.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, i) {
          final hours = periods[i];
          final selected = hours == _hotspotTimeWindowHours;
          return GestureDetector(
            onTap: () {
              if (selected) return;
              debugPrint('Filter tapped: ${_formatHotspotWindow(hours)} ($hours hours)');
              setState(() => _hotspotTimeWindowHours = hours);
              if (_userLat != null && _userLng != null) {
                _loadHotspots();
                _loadPublicAlerts();
              }
            },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 150),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              decoration: BoxDecoration(
                color: selected
                    ? AppColors.accent.withValues(alpha: 0.15)
                    : AppColors.surface2,
                border: Border.all(
                  color: selected ? AppColors.accent : AppColors.border,
                ),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(
                _formatHotspotWindow(hours),
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.normal,
                  color: selected ? AppColors.accent : AppColors.muted,
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildNearbyRadiusFilters() {
    const radii = <int>[500, 1500, 3000];
    final hasLocation = _userLat != null && _userLng != null;
    return Container(
      height: 34,
      margin: const EdgeInsets.fromLTRB(20, 8, 20, 0),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: radii.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, i) {
          final meters = radii[i];
          final selected = meters == _nearbyHotspotRadiusMeters;
          return GestureDetector(
            onTap: !hasLocation
                ? null
                : () {
                    if (selected) return;
                    setState(() {
                      _nearbyHotspotRadiusMeters = meters;
                      _distanceController.text = _distanceInKm
                          ? (meters / 1000).toStringAsFixed(1)
                          : meters.toStringAsFixed(0);
                    });
                    unawaited(ProximityAlertService().updateRadius(meters.toDouble()));
                    _loadHotspots();
                    _loadPublicAlerts();
                  },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 150),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              decoration: BoxDecoration(
                color: selected
                    ? AppColors.accent2.withValues(alpha: 0.15)
                    : AppColors.surface2,
                border: Border.all(
                  color: selected ? AppColors.accent2 : AppColors.border,
                ),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(
                hasLocation
                    ? 'Within ${meters < 1000 ? '${meters}m' : '${(meters / 1000).toStringAsFixed(1)} km'}'
                    : 'Enable GPS',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.normal,
                  color: hasLocation
                      ? (selected ? AppColors.accent2 : AppColors.muted)
                      : AppColors.muted,
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildDistanceInput() {
    final hasLocation = _userLat != null && _userLng != null;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
      child: Row(
        children: [
          const Icon(Icons.radar, size: 14, color: AppColors.muted),
          const SizedBox(width: 6),
          const Text(
            'Nearby radius:',
            style: TextStyle(fontSize: 12, color: AppColors.muted),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 64,
            height: 32,
            child: TextField(
              controller: _distanceController,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              textAlign: TextAlign.center,
              enabled: hasLocation,
              style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.text),
              decoration: InputDecoration(
                contentPadding: const EdgeInsets.symmetric(
                    horizontal: 6, vertical: 6),
                filled: true,
                fillColor: AppColors.surface2,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide:
                      const BorderSide(color: AppColors.border),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide:
                      const BorderSide(color: AppColors.border),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide:
                      const BorderSide(color: AppColors.accent),
                ),
              ),
              onSubmitted: (_) => _applyDistanceInput(),
              onEditingComplete: _applyDistanceInput,
            ),
          ),
          const SizedBox(width: 6),
          // km / m toggle
          GestureDetector(
            onTap: hasLocation
                ? () {
                    setState(() => _distanceInKm = !_distanceInKm);
                    _applyDistanceInput();
                  }
                : null,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 150),
              padding: const EdgeInsets.symmetric(
                  horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: AppColors.accent.withValues(alpha: 0.14),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(
                    color: AppColors.accent.withValues(alpha: 0.5)),
              ),
              child: Text(
                _distanceInKm ? 'km' : 'm',
                style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: AppColors.accent),
              ),
            ),
          ),
          const SizedBox(width: 8),
          if (!hasLocation)
            const Text(
              'Enable GPS',
              style: TextStyle(fontSize: 11, color: AppColors.muted),
            ),
        ],
      ),
    );
  }

  void _applyDistanceInput() {
    final raw = double.tryParse(_distanceController.text.trim());
    if (raw == null || raw <= 0) return;
    final meters = _distanceInKm ? (raw * 1000).round() : raw.round();
    final clamped = meters.clamp(100, 20000);
    if (clamped == _nearbyHotspotRadiusMeters) return;
    setState(() => _nearbyHotspotRadiusMeters = clamped);
    // Keep the proximity alert service in sync with the map radius so alerts
    // fire for the same distance the user has selected on the map.
    unawaited(ProximityAlertService().updateRadius(clamped.toDouble()));
    if (_userLat != null && _userLng != null) {
      _loadHotspots();
      _loadPublicAlerts();
    }
  }

  Widget _buildMap() {
    if (_loading) {
      return const Center(
          child: CircularProgressIndicator(color: AppColors.accent));
    }
    if (_mapData == null) {
      return Center(
          child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.map_outlined, color: AppColors.muted, size: 48),
            const SizedBox(height: 12),
            const Text('Could not load map data',
                style: TextStyle(fontWeight: FontWeight.w600)),
            if (_error != null) ...[
              const SizedBox(height: 6),
              Text(_error!,
                  style:
                      const TextStyle(fontSize: 11, color: AppColors.muted),
                  textAlign: TextAlign.center),
            ],
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: () {
                setState(() {
                  _loading = true;
                  _error = null;
                });
                _loadMap();
              },
              icon: const Icon(Icons.refresh, size: 16),
              label: const Text('Retry'),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.accent,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10)),
              ),
            ),
          ],
        ),
      ));
    }

    return Container(
      margin: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          FlutterMap(
            mapController: _mapController,
            options: MapOptions(
              initialCenter: _musanzeCenter,
              initialZoom: _initialZoom,
              minZoom: 10,
              maxZoom: 18,
              interactionOptions: const InteractionOptions(
                flags: InteractiveFlag.all,
              ),
            ),
            children: [
              // OSM tile layer — includes roads, buildings, terrain
              TileLayer(
                urlTemplate:
                    'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.trustbond.mobile',
                maxZoom: 18,
              ),
              // Village polygon overlays (before dark overlay to show colors)
              PolygonLayer(polygons: _buildPolygons()),
              // Semi-transparent dark overlay for readability (reduced opacity)
              ColoredBox(
                color: AppColors.bg.withValues(alpha: 0.15),
                child: const SizedBox.expand(),
              ),
              // Labels (sector/cell/village)
              MarkerLayer(markers: _buildRegionLabels()),
              // Hotspot pins
              MarkerLayer(markers: _buildHotspotMarkers()),
              // User GPS marker
              MarkerLayer(markers: _buildUserMarker()),
            ],
          ),
          // Zoom controls
          Positioned(
            right: 10,
            bottom: 50,
            child: Column(
              children: [
                _mapButton(Icons.add, () {
                  final zoom = _mapController.camera.zoom + 1;
                  _mapController.move(
                      _mapController.camera.center, zoom.clamp(10, 18));
                }),
                const SizedBox(height: 6),
                _mapButton(Icons.remove, () {
                  final zoom = _mapController.camera.zoom - 1;
                  _mapController.move(
                      _mapController.camera.center, zoom.clamp(10, 18));
                }),
                const SizedBox(height: 6),
                if (_userLat != null)
                  _mapButton(Icons.my_location, _centerOnUser),
              ],
            ),
          ),
          if (_locatingUser)
            Positioned(
              top: 8,
              right: 10,
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.bg.withValues(alpha: 0.85),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SizedBox(
                      width: 10,
                      height: 10,
                      child: CircularProgressIndicator(
                          strokeWidth: 1.5, color: AppColors.accent),
                    ),
                    SizedBox(width: 6),
                    Text('Locating...',
                        style:
                            TextStyle(fontSize: 9, color: AppColors.muted)),
                  ],
                ),
              ),
            ),
          // District / Sector label
          Positioned(
            bottom: 8,
            left: 10,
            child: Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.bg.withValues(alpha: 0.85),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                _selectedSector ?? 'Musanze District',
                style: const TextStyle(
                    fontSize: 10,
                    color: AppColors.muted,
                    fontFamily: 'monospace'),
              ),
            ),
          ),
          Positioned(
            bottom: 8,
            right: 10,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: AppColors.bg.withValues(alpha: 0.85),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.border),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _LegendDot(color: AppColors.danger),
                  SizedBox(width: 5),
                  Text(
                    'Higher activity',
                    style: TextStyle(fontSize: 10, color: AppColors.muted),
                  ),
                  SizedBox(width: 10),
                  _LegendDot(color: AppColors.accent),
                  SizedBox(width: 5),
                  Text(
                    'Lower activity',
                    style: TextStyle(fontSize: 10, color: AppColors.muted),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Location status above the map — light card so text is always readable on dark UI.
  Widget _buildLocationStatusStrip() {
    if (_userLat == null || _userLng == null) {
      return const SizedBox.shrink();
    }

    final outside = _userVillage == null;
    if (outside &&
        (_userLocationCaption == null || _userLocationCaption!.trim().isEmpty)) {
      return const SizedBox.shrink();
    }

    // Cream / mint cards with dark text (high contrast on dark scaffold).
    final bg = outside ? const Color(0xFFFFF7ED) : const Color(0xFFECFDF5);
    final accent = outside ? const Color(0xFFC2410C) : const Color(0xFF047857);
    final bodyColor = const Color(0xFF1E293B);
    final mutedColor = const Color(0xFF475569);

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
      child: Material(
        color: bg,
        elevation: 1,
        shadowColor: Colors.black26,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: accent.withValues(alpha: 0.45)),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                outside ? Icons.location_off_outlined : Icons.my_location,
                size: 20,
                color: accent,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: DefaultTextStyle(
                  style: TextStyle(
                    fontSize: 13,
                    color: bodyColor,
                    fontWeight: FontWeight.w500,
                    height: 1.3,
                  ),
                  child: outside
                      ? Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Outside Musanze District',
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w800,
                                color: accent,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'Your GPS: ${_userLocationCaption!}',
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                                color: bodyColor,
                              ),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              'Map shows Musanze; your pin is your real position.',
                              style: TextStyle(fontSize: 12, color: mutedColor),
                            ),
                          ],
                        )
                      : Text(
                          'You are in ${_userVillage!.village}, ${_userVillage!.cell}',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: accent,
                          ),
                        ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _mapButton(IconData icon, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 36,
        height: 36,
        decoration: BoxDecoration(
          color: AppColors.bg.withValues(alpha: 0.85),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AppColors.border),
        ),
        child: Icon(icon, size: 18, color: AppColors.text),
      ),
    );
  }

  Widget _buildSectorInfo() {
    // Always show nearby AI recommendation panel.
    return Container(
      height: 150,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.surface2,
        border: Border(top: BorderSide(color: AppColors.border.withValues(alpha: 0.3))),
      ),
      child: _buildNearbyAlerts(),
    );
  }

  Widget _buildNearbyAlerts() {
    if (_userLat == null || _userLng == null) {
      return const Center(
        child: Text(
          'Enable location to get nearby safety recommendations',
          style: TextStyle(fontSize: 12, color: AppColors.muted),
          textAlign: TextAlign.center,
        ),
      );
    }

    if (_loadingAlerts) {
      return const Center(
        child: Text(
          'Analyzing nearby safety alerts...',
          style: TextStyle(fontSize: 12, color: AppColors.muted),
        ),
      );
    }

    if (_publicAlerts.isEmpty) {
      return const Center(
        child: Text(
          'No safety alerts near you. See something? Tap + to report it.',
          style: TextStyle(fontSize: 12, color: AppColors.muted),
          textAlign: TextAlign.center,
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Nearby AI Safety Alerts (${_alertsRadiusKm.toStringAsFixed(1)} km)',
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: _publicAlerts.length,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (context, i) {
              final a = _publicAlerts[i];
              final title = (a['title'] ?? 'Safety Alert').toString();
              final msg = (a['message'] ?? '').toString();
              final dist = (a['distance_km'] ?? '').toString();
              final sev = (a['severity'] ?? 'info').toString().toLowerCase();
              final color = sev == 'high'
                  ? AppColors.danger
                  : sev == 'medium'
                      ? AppColors.warn
                      : AppColors.ok;

              return Container(
                width: 240,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.08),
                  border: Border.all(color: color.withValues(alpha: 0.3)),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: color,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Expanded(
                      child: Text(
                        msg,
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 10),
                      ),
                    ),
                    if (dist.isNotEmpty)
                      Text(
                        '$dist km away',
                        style: const TextStyle(fontSize: 10, color: AppColors.muted),
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
}

class _LegendDot extends StatelessWidget {
  final Color color;

  const _LegendDot({required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
      ),
    );
  }
}

