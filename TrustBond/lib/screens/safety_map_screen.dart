import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'dart:ui' as ui;
import '../config/theme.dart';
import '../models/musanze_map_data.dart';
import '../services/location_service.dart';
import '../services/api_service.dart';
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
  bool _loading = true;
  String? _error;

  // Detail level management
  bool _showDetailedView = false;
  String _currentDetailLevel = 'sector'; // 'sector', 'cell', 'village'

  // GPS location state
  final _locationService = LocationService();
  final _api = ApiService();
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

  @override
  void initState() {
    super.initState();
    _showDetailedView = widget.showDetailedView;
    _loadMap();
    _loadSectorsFromBackend();
    _getUserLocation();
    
    // If coming from home screen with detailed view, show all sectors initially
    if (_showDetailedView) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        // Start with a slightly zoomed in view for better detail
        _mapController.move(_musanzeCenter, 14.0);
        setState(() {
          _currentDetailLevel = 'sector'; // Start at sector level for detailed view
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

  Future<void> _getUserLocation() async {
    setState(() => _locatingUser = true);
    try {
      final result = await _locationService.getFullLocation();
      if (result.hasPosition && mounted) {
        setState(() {
          _userLat = result.latitude;
          _userLng = result.longitude;
          _userVillage = result.village;
          _locatingUser = false;
        });
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
          _loading = false;
        });
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

  /// Build polygon layers from GeoJSON data.
  List<Polygon> _buildPolygons() {
    if (_mapData == null) return [];
    final polygons = <Polygon>[];

    for (final feature in _mapData!.features) {
      final isHighlighted =
          _selectedSector == null || feature.sector == _selectedSector;
      final baseColor = sectorColor(feature.sector);

      for (final ring in feature.rings) {
        if (ring.length < 3) continue;
        final points = ring.map((pt) => LatLng(pt.dy, pt.dx)).toList();
        polygons.add(Polygon(
          points: points,
          color: isHighlighted
              ? baseColor.withValues(alpha: 0.20)
              : baseColor.withValues(alpha: 0.05),
          borderColor: isHighlighted
              ? baseColor.withValues(alpha: 0.6)
              : baseColor.withValues(alpha: 0.15),
          borderStrokeWidth: isHighlighted ? 1.2 : 0.4,
        ));
      }
    }
    return polygons;
  }

  /// Build sector label markers.
  List<Marker> _buildSectorLabels() {
    if (_mapData == null) return [];
    final markers = <Marker>[];

    for (final sector in _mapData!.sectors) {
      if (_selectedSector != null && sector != _selectedSector) continue;
      final centroid = _mapData!.sectorCentroid(sector);
      final color = sectorColor(sector);

      markers.add(Marker(
        point: LatLng(centroid.dy, centroid.dx),
        width: 90,
        height: 24,
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: AppColors.bg.withValues(alpha: 0.75),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              sector,
              style: TextStyle(
                fontSize: _selectedSector != null ? 11 : 9,
                fontWeight: FontWeight.w600,
                color: color,
              ),
              textAlign: TextAlign.center,
            ),
          ),
        ),
      ));
    }
    return markers;
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
            _buildSectorFilters(),
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
                  _mapData != null
                      ? '${_mapData!.features.length} villages'
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
          final color =
              i == 0 ? AppColors.accent2 : sectorColor(name);
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
                _cells = [];
                _villages = [];
              });
              if (i > 0 && _mapData != null) {
                final centroid = _mapData!.sectorCentroid(name);
                _mapController.move(
                    LatLng(centroid.dy, centroid.dx), 14.5);
                if (sectorId != null) {
                  _loadCells(sectorId);
                }
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
                    'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.trustbond.mobile',
                maxZoom: 18,
              ),
              // Semi-transparent dark overlay for readability
              ColoredBox(
                color: AppColors.bg.withValues(alpha: 0.3),
                child: const SizedBox.expand(),
              ),
              // Village polygon overlays
              PolygonLayer(polygons: _buildPolygons()),
              // Sector labels
              MarkerLayer(markers: _buildSectorLabels()),
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
          // Current location banner
          if (_userVillage != null)
            Positioned(
              top: 8,
              left: 10,
              right: 60,
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: AppColors.accent.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                      color: AppColors.accent.withValues(alpha: 0.3)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.my_location,
                        size: 14, color: AppColors.accent),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        'You are in ${_userVillage!.village}, ${_userVillage!.cell}',
                        style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.accent,
                            fontWeight: FontWeight.w600),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
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
        ],
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
    // Always return a visible container that fills the space
    return Container(
      height: 150,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.surface2,
        border: Border(top: BorderSide(color: AppColors.border.withValues(alpha: 0.3))),
      ),
      child: _buildSectorContent(),
    );
  }

  Widget _buildSectorContent() {
    if (_mapData == null) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(color: AppColors.accent, strokeWidth: 2),
            SizedBox(height: 8),
            Text('Loading map data...', style: TextStyle(fontSize: 12, color: AppColors.muted)),
          ],
        ),
      );
    }

    // Drill-down (old UI style):
    // - No sector selected: show sector cards.
    // - Sector selected: show cells list from backend; tap cell to show villages list.
    // - Cell selected: show villages list from backend; tap village to move camera.

    if (_selectedSector == null) {
      final sectors = _mapData!.sectors;
      debugPrint('Showing ${sectors.length} sectors in info panel');
      return ListView.builder(
        itemCount: sectors.length,
        itemBuilder: (context, i) {
          final name = sectors[i];
          final villages = _mapData!.bySector(name);
          final cells = _mapData!.cellsIn(name);
          final color = sectorColor(name);
          return GestureDetector(
            onTap: () {
              int? sectorId;
              if (_sectors.isNotEmpty) {
                final match = _sectors.firstWhere(
                  (s) => (s['location_name'] ?? '').toString() == name,
                  orElse: () => {},
                );
                final id = match['location_id'];
                if (id is int) sectorId = id;
              }
              setState(() {
                _selectedSector = name;
                _selectedSectorId = sectorId;
                _selectedCellId = null;
                _selectedCellName = null;
                _cells = [];
                _villages = [];
              });
              final centroid = _mapData!.sectorCentroid(name);
              _mapController.move(LatLng(centroid.dy, centroid.dx), 14.5);
              if (sectorId != null) {
                _loadCells(sectorId);
              }
            },
            child: Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppColors.card,
                border: Border.all(color: AppColors.border),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: color.withValues(alpha: 0.12),
                    ),
                    child: Icon(Icons.location_on_rounded, size: 18, color: color),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(name, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                        Text(
                          '${cells.length} cells · ${villages.length} villages',
                          style: const TextStyle(fontSize: 10, color: AppColors.muted),
                        ),
                      ],
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: color.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      '${villages.length}',
                      style: TextStyle(fontSize: 10, color: color, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      );
    }

    // When a sector is selected, show cells or villages
    final sectorColorC = sectorColor(_selectedSector!);
    final showingVillages = _selectedCellId != null;
    final items = showingVillages ? _villages : _cells;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            children: [
              Text(
                showingVillages ? 'Villages in $_selectedCellName' : 'Cells in $_selectedSector',
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AppColors.text),
              ),
              const Spacer(),
              GestureDetector(
                onTap: () {
                  setState(() {
                    _selectedSector = null;
                    _selectedSectorId = null;
                    _selectedCellId = null;
                    _selectedCellName = null;
                    _cells = [];
                    _villages = [];
                  });
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.muted.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: const Text('Back', style: TextStyle(fontSize: 10, color: AppColors.muted)),
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: items.isEmpty
              ? const Center(
                  child: Text('No data available', style: TextStyle(fontSize: 11, color: AppColors.muted)),
                )
              : ListView.builder(
                  itemCount: items.length,
                  itemBuilder: (context, index) {
                    final item = items[index];
                    final name = item['location_name']?.toString() ?? 'Unknown';
                    return GestureDetector(
                      onTap: () {
                        if (showingVillages) {
                          // Move to village location
                          final lat = item['latitude'] as double?;
                          final lng = item['longitude'] as double?;
                          if (lat != null && lng != null) {
                            _mapController.move(LatLng(lat, lng), 16.0);
                          }
                        } else {
                          // Load villages for this cell
                          final cellId = item['location_id'] as int?;
                          if (cellId != null) {
                            _loadVillages(cellId);
                            setState(() {
                              _selectedCellId = cellId;
                              _selectedCellName = name;
                            });
                          }
                        }
                      },
                      child: Container(
                        margin: const EdgeInsets.only(bottom: 4),
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: AppColors.card,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Row(
                          children: [
                            Container(
                              width: 24,
                              height: 24,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: sectorColorC.withValues(alpha: 0.12),
                              ),
                              child: showingVillages 
                                  ? Icon(Icons.home_outlined, size: 12, color: sectorColorC)
                                  : Icon(Icons.grid_view_outlined, size: 12, color: sectorColorC),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(name, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w500)),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Future<void> _loadDetailedView(String sectorId) async {
    try {
      // Parse sector ID to int if needed
      final sectorIdInt = int.tryParse(sectorId);
      if (sectorIdInt != null) {
        await _loadCells(sectorIdInt);
        setState(() {
          _currentDetailLevel = 'cell';
          _selectedSectorId = sectorIdInt;
        });
        
        // Zoom to sector level
        final sector = _sectors.firstWhere((s) => s['location_id'] == sectorIdInt, 
            orElse: () => {});
        if (sector.isNotEmpty) {
          final lat = sector['latitude'] as double?;
          final lng = sector['longitude'] as double?;
          if (lat != null && lng != null) {
            _mapController.move(LatLng(lat, lng), 14.0);
          }
        }
      }
    } catch (e) {
      debugPrint('Error loading detailed view: $e');
    }
  }
}

