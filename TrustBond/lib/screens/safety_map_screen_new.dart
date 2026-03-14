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
import '../widgets/musanze_map_painter.dart' show sectorColor;

class SafetyMapScreen extends StatefulWidget {
  const SafetyMapScreen({super.key});

  @override
  State<SafetyMapScreen> createState() => _SafetyMapScreenState();
}

class _SafetyMapScreenState extends State<SafetyMapScreen> {
  MusanzeMapData? _mapData;
  String? _selectedSector;
  int? _selectedSectorId;
  int? _selectedCellId;
  String? _selectedCellName;
  bool _loading = true;
  String? _error;

  // GPS location state
  final _locationService = LocationService();
  final _api = ApiService();
  final _hotspotService = HotspotService();
  double? _userLat;
  double? _userLng;
  VillageLocation? _userVillage;
  bool _locatingUser = false;

  final MapController _mapController = MapController();

  // Musanze District center
  static const _musanzeCenter = LatLng(-1.4975, 29.6347);
  static const double _initialZoom = 13.0;

  // Backend hierarchy lists
  List<Map<String, dynamic>> _sectors = [];
  List<Map<String, dynamic>> _cells = [];
  List<Map<String, dynamic>> _villages = [];
  bool _loadingHierarchy = false;

  // Hotspot data
  List<Hotspot> _villageHotspots = [];
  List<Hotspot> _cellHotspots = [];
  bool _loadingHotspots = false;
  String _currentHotspotLevel = 'village'; // village or cell

  @override
  void initState() {
    super.initState();
    _loadMap();
    _loadSectorsFromBackend();
    _getUserLocation();
  }

  Future<void> _loadMap() async {
    try {
      final data = await MusanzeMapData.load();
      if (mounted) setState(() => _mapData = data);
    } catch (e) {
      if (mounted) setState(() => _error = 'Failed to load map: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadSectorsFromBackend() async {
    setState(() => _loadingHierarchy = true);
    try {
      final res = await _api.getPublicLocations(locationType: 'sector', limit: 1000);
      if (!mounted) return;
      setState(() {
        _sectors = res.cast<Map<String, dynamic>>();
        _loadingHierarchy = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loadingHierarchy = false);
    }
  }

  Future<void> _loadVillageHotspots(int sectorId) async {
    setState(() {
      _loadingHotspots = true;
      _villageHotspots = [];
      _cellHotspots = [];
      _currentHotspotLevel = 'village';
    });
    
    try {
      final hotspots = await _hotspotService.getVillageHotspots(sectorId);
      if (!mounted) return;
      setState(() {
        _villageHotspots = hotspots;
        _loadingHotspots = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loadingHotspots = false);
    }
  }

  Future<void> _loadCellHotspots(int sectorId) async {
    setState(() {
      _loadingHotspots = true;
      _villageHotspots = [];
      _cellHotspots = [];
      _currentHotspotLevel = 'cell';
    });
    
    try {
      final hotspots = await _hotspotService.getCellHotspots(sectorId: sectorId);
      if (!mounted) return;
      setState(() {
        _cellHotspots = hotspots;
        _loadingHotspots = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loadingHotspots = false);
    }
  }

  void _toggleHotspotLevel() {
    if (_selectedSectorId == null) return;
    
    if (_currentHotspotLevel == 'village') {
      _loadCellHotspots(_selectedSectorId!);
    } else {
      _loadVillageHotspots(_selectedSectorId!);
    }
  }

  List<Hotspot> get _currentHotspots {
    return _currentHotspotLevel == 'village' ? _villageHotspots : _cellHotspots;
  }

  Future<void> _getUserLocation() async {
    setState(() => _locatingUser = true);
    try {
      final result = await _locationService.getFullLocation();
      if (mounted && result.hasPosition) {
        setState(() {
          _userLat = result.latitude;
          _userLng = result.longitude;
          _userVillage = result.village;
        });
      }
    } catch (_) {}
    if (mounted) setState(() => _locatingUser = false);
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
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
                TileLayer(
                  urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                  userAgentPackageName: 'com.trustbond.mobile',
                  maxZoom: 18,
                ),
                ColoredBox(
                  color: AppColors.bg.withValues(alpha: 0.3),
                  child: const SizedBox.expand(),
                ),
                MarkerLayer(markers: _buildHotspotMarkers()),
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
                    _mapController.move(_mapController.camera.center, zoom.clamp(10, 18));
                  }),
                  const SizedBox(height: 6),
                  _mapButton(Icons.remove, () {
                    final zoom = _mapController.camera.zoom - 1;
                    _mapController.move(_mapController.camera.center, zoom.clamp(10, 18));
                  }),
                  const SizedBox(height: 6),
                  if (_userLat != null)
                    _mapButton(Icons.my_location, _centerOnUser),
                  const SizedBox(height: 6),
                  if (_selectedSectorId != null)
                    _mapButton(
                      _currentHotspotLevel == 'village' ? Icons.location_city : Icons.home,
                      _toggleHotspotLevel,
                      tooltip: _currentHotspotLevel == 'village' 
                          ? 'Switch to Cell Level' 
                          : 'Switch to Village Level',
                    ),
                ],
              ),
            ),
            // Current location banner
            if (_userVillage != null)
              Positioned(
                top: 8,
                left: 10,
                right: 60,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: AppColors.accent.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    'You are in ${_userVillage!.village}, ${_userVillage!.cell}',
                    style: const TextStyle(fontSize: 10, color: AppColors.accent),
                  ),
                ),
              ),
            // Loading indicator
            if (_locatingUser)
              const Positioned(
                top: 8,
                right: 10,
                child: SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    color: AppColors.accent,
                    strokeWidth: 2,
                  ),
                ),
              ),
            // Bottom sheet for sector info
            Positioned(
              bottom: 0,
              left: 0,
              right: 0,
              child: _buildSectorInfo(),
            ),
          ],
        ),
      ),
    );
  }

  Widget _mapButton(IconData icon, VoidCallback onTap, {String? tooltip}) {
    Widget button = GestureDetector(
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
    
    if (tooltip != null) {
      return Tooltip(
        message: tooltip,
        child: button,
      );
    }
    
    return button;
  }

  List<Marker> _buildHotspotMarkers() {
    if (_currentHotspots.isEmpty) return [];
    
    return _currentHotspots.map((hotspot) {
      return Marker(
        point: LatLng(hotspot.centerLat, hotspot.centerLong),
        width: 40,
        height: 40,
        child: GestureDetector(
          onTap: () => _showHotspotDetails(hotspot),
          child: Stack(
            alignment: Alignment.center,
            children: [
              if (hotspot.riskLevel == 'high')
                Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(
                    color: _getHotspotColor(hotspot.riskLevel).withValues(alpha: 0.3),
                    shape: BoxShape.circle,
                  ),
                ),
              Container(
                width: 20,
                height: 20,
                decoration: BoxDecoration(
                  color: _getHotspotColor(hotspot.riskLevel),
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.bg, width: 2),
                  boxShadow: [
                    BoxShadow(
                      color: _getHotspotColor(hotspot.riskLevel).withValues(alpha: 0.3),
                      blurRadius: 4,
                      spreadRadius: 1,
                    ),
                  ],
                ),
              ),
              Positioned(
                right: 0,
                top: 0,
                child: Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: _getHotspotColor(hotspot.riskLevel),
                    shape: BoxShape.circle,
                    border: Border.all(color: AppColors.bg, width: 1),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    }).toList();
  }

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

  void _showHotspotDetails(Hotspot hotspot) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Row(
          children: [
            Text(hotspot.riskEmoji),
            const SizedBox(width: 8),
            Text(hotspot.riskText),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Incidents: ${hotspot.incidentCount}'),
            if (hotspot.incidentTypeName != null)
              Text('Type: ${hotspot.incidentTypeName}'),
            Text('Time window: ${hotspot.timeWindowHours} hours'),
            Text('Radius: ${hotspot.radiusMeters.toStringAsFixed(0)}m'),
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

  Color _getHotspotColor(String riskLevel) {
    switch (riskLevel) {
      case 'high':
        return AppColors.danger;
      case 'medium':
        return AppColors.warn;
      case 'low':
        return AppColors.ok;
      default:
        return AppColors.muted;
    }
  }

  void _centerOnUser() {
    if (_userLat != null && _userLng != null) {
      _mapController.move(LatLng(_userLat!, _userLng!), 15.0);
    }
  }

  Widget _buildSectorInfo() {
    if (_mapData == null) return const SizedBox.shrink();

    if (_selectedSector == null) {
      final sectors = _mapData!.sectors;
      return Container(
        constraints: const BoxConstraints(maxHeight: 170),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.bg,
          border: Border(top: BorderSide(color: AppColors.border)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  'Musanze District · ${_currentHotspots.length} hotspots',
                  style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                ),
                const Spacer(),
                if (_loadingHotspots)
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      color: AppColors.accent,
                      strokeWidth: 2,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Expanded(
              child: ListView.separated(
                padding: EdgeInsets.zero,
                itemCount: sectors.length + 1, // +1 for "All sectors"
                separatorBuilder: (_, __) => const SizedBox(height: 6),
                itemBuilder: (context, i) {
                  final name = i == 0 ? null : sectors[i - 1];
                  final sel = i == 0 && _selectedSector == null;
                  final color = i == 0 ? AppColors.accent2 : sectorColor(name!);
                  
                  return ListTile(
                    dense: true,
                    leading: Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: color,
                        shape: BoxShape.circle,
                      ),
                    ),
                    title: Text(
                      i == 0 ? 'All Sectors' : name!,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: sel ? FontWeight.w600 : FontWeight.normal,
                        color: sel ? color : AppColors.text,
                      ),
                    ),
                    onTap: () {
                      if (i == 0) {
                        setState(() {
                          _selectedSector = null;
                          _selectedSectorId = null;
                          _villageHotspots = [];
                          _cellHotspots = [];
                        });
                        _mapController.move(_musanzeCenter, _initialZoom);
                      } else {
                        setState(() {
                          _selectedSector = name;
                          _selectedSectorId = null; // Will be set when backend loads
                        });
                        // Load sector-specific hotspots
                        _loadVillageHotspots(1); // Use sector ID 1 for now
                      }
                    },
                  );
                },
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      height: 120,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.bg,
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '${_selectedSector ?? 'Sector'} · ${_currentHotspots.length} hotspots',
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
              ),
              const Spacer(),
              if (_loadingHotspots)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    color: AppColors.accent,
                    strokeWidth: 2,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '$_currentHotspotLevel level hotspots shown',
            style: const TextStyle(fontSize: 11, color: AppColors.muted),
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              TextButton(
                onPressed: () {
                  setState(() {
                    _selectedSector = null;
                    _selectedSectorId = null;
                    _villageHotspots = [];
                    _cellHotspots = [];
                  });
                  _mapController.move(_musanzeCenter, _initialZoom);
                },
                child: const Text('Back to All'),
              ),
              const Spacer(),
              TextButton(
                onPressed: _toggleHotspotLevel,
                child: Text('Switch to ${_currentHotspotLevel == 'village' ? 'Cell' : 'Village'}'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
