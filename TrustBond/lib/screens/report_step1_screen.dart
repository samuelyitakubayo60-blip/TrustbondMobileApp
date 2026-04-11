import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../services/api_service.dart';
import '../services/local_cache_service.dart';
import 'report_step2_screen.dart';

class ReportStep1Screen extends StatefulWidget {
  const ReportStep1Screen({super.key});

  @override
  State<ReportStep1Screen> createState() => _ReportStep1ScreenState();
}

class _ReportStep1ScreenState extends State<ReportStep1Screen> {
  final _apiService = ApiService();
  final _cache = LocalCacheService();
  List<Map<String, dynamic>> _types = [];
  bool _loading = true;
  String? _error;
  bool _showingCached = false;
  int? _selectedTypeId;
  String? _selectedTypeName;

  @override
  void initState() {
    super.initState();
    _loadTypes();
  }

  Future<void> _loadTypes() async {
    try {
      final data = await _apiService.getIncidentTypes();
      await _cache.cacheIncidentTypes(data);
      setState(() {
        _types = List<Map<String, dynamic>>.from(
          data.map((e) => Map<String, dynamic>.from(e as Map)),
        );
        _showingCached = false;
        _loading = false;
      });
    } catch (e) {
      final cached = await _cache.getCachedIncidentTypes();
      if (cached.isNotEmpty) {
        setState(() {
          _types = cached;
          _showingCached = true;
          _loading = false;
          _error = null;
        });
        return;
      }

      debugPrint('Failed to load incident types: $e');
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildAppBar(),
            const StepIndicators(current: 0, total: 3),
            Expanded(child: _buildBody()),
            _buildContinueButton(),
          ],
        ),
      ),
    );
  }

  Widget _buildAppBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 20, 0),
      child: Row(
        children: [
          IconButton(
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.arrow_back_ios_new, size: 18),
          ),
          const Expanded(
            child: Text(
              'New Report',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
            ),
          ),
          const Text('Step 1 of 3',
              style: TextStyle(fontSize: 11, color: AppColors.muted)),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(
          child: CircularProgressIndicator(color: AppColors.accent));
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off, color: AppColors.muted, size: 48),
              const SizedBox(height: 12),
              const Text('Could not load incident types',
                  style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              Text(_error!, style: const TextStyle(fontSize: 12, color: AppColors.muted), textAlign: TextAlign.center),
              const SizedBox(height: 16),
              ElevatedButton.icon(
                onPressed: () {
                  setState(() { _loading = true; _error = null; });
                  _loadTypes();
                },
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Retry'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
              ),
            ],
          ),
        ),
      );
    }
    if (_types.isEmpty) {
      return const Center(
        child: Text('No incident types available.\nCheck your connection and try again.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.muted)),
      );
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_showingCached)
            Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: AppColors.surface2,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: AppColors.border),
              ),
              child: const Row(
                children: [
                  Icon(Icons.wifi_off, size: 14, color: AppColors.muted),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Offline mode: using last synced incident types.',
                      style: TextStyle(fontSize: 11, color: AppColors.muted),
                    ),
                  ),
                ],
              ),
            ),
          const Text('What type of incident?',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          const Text('Select the category that best describes what happened',
              style: TextStyle(fontSize: 12, color: AppColors.muted)),
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              final crossSpacing = 10.0;
              final mainSpacing = 10.0;
              final count = 2;
              final itemWidth = (constraints.maxWidth - crossSpacing) / count;
              final itemHeight = itemWidth * 0.95;
              return Wrap(
                spacing: crossSpacing,
                runSpacing: mainSpacing,
                children: List.generate(_types.length, (index) {
                  final t = _types[index];
                  final id = t['incident_type_id'] as int? ?? 0;
                  final name = t['type_name'] as String? ?? '';
                  final sel = _selectedTypeId == id;
                  return SizedBox(
                    width: itemWidth,
                    height: itemHeight,
                    child: _buildTypeCard(id, name, sel),
                  );
                }),
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _buildTypeCard(int id, String name, bool selected) {
    final icon = iconForIncidentType(name);
    final color = colorForIncidentType(name);
    return GestureDetector(
      onTap: () => setState(() {
        _selectedTypeId = id;
        _selectedTypeName = name;
      }),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
        decoration: BoxDecoration(
          color: selected
              ? color.withValues(alpha: 0.12)
              : AppColors.card,
          border: Border.all(
            color: selected ? color : AppColors.border,
            width: selected ? 1.5 : 1,
          ),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Fixed-size icon so all incident types look the same (no oversized emoji)
            SizedBox(
              height: 26,
              width: 26,
              child: Center(
                child: Text(
                  icon,
                  style: const TextStyle(fontSize: 20),
                  textScaler: TextScaler.linear(1.0),
                  overflow: TextOverflow.clip,
                ),
              ),
            ),
            const SizedBox(height: 6),
            Text(
              name,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: selected ? color : AppColors.text,
              ),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildContinueButton() {
    final enabled = _selectedTypeId != null;
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 16),
      child: SizedBox(
        width: double.infinity,
        height: 50,
        child: ElevatedButton(
          onPressed: enabled
              ? () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => ReportStep2Screen(
                        incidentTypeId: _selectedTypeId!,
                        incidentTypeName: _selectedTypeName ?? '',
                      )))
              : null,
          style: ElevatedButton.styleFrom(
            backgroundColor: enabled ? AppColors.accent : AppColors.surface2,
            foregroundColor: enabled ? AppColors.bg : AppColors.muted,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14)),
          ),
          child: const Text('Continue',
              style: TextStyle(fontWeight: FontWeight.w700)),
        ),
      ),
    );
  }

}
