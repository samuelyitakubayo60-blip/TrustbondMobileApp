import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../models/musanze_map_data.dart';
import '../services/location_service.dart';
import '../widgets/shared_widgets.dart';
import 'report_step3_screen.dart';

class ReportStep2Screen extends StatefulWidget {
  final int incidentTypeId;
  final String incidentTypeName;

  const ReportStep2Screen({
    super.key,
    required this.incidentTypeId,
    required this.incidentTypeName,
  });

  @override
  State<ReportStep2Screen> createState() => _ReportStep2ScreenState();
}

class _ReportStep2ScreenState extends State<ReportStep2Screen> {
  final _descController = TextEditingController();
  final _locationService = LocationService();
  double? _latitude;
  double? _longitude;
  double? _gpsAccuracy;
  VillageLocation? _villageLocation;
  bool _locating = false;
  String? _locError;
  bool _canOpenSettings = false;
  final List<String> _selectedTags = [];

  static const _tags = [
    'Night-time',
    'Weapons involved',
    'Multiple suspects',
    'Victim present',
    'Vehicle involved',
    'Ongoing',
  ];

  @override
  void initState() {
    super.initState();
    _descController.addListener(() => setState(() {}));
    _getLocation();
  }

  Future<void> _getLocation() async {
    setState(() {
      _locating = true;
      _locError = null;
      _canOpenSettings = false;
      _villageLocation = null;
    });
    try {
      final result = await _locationService.getFullLocation();
      if (result.hasError) {
        setState(() {
          _locError = result.error;
          _canOpenSettings = result.canOpenSettings;
          _locating = false;
        });
        return;
      }
      setState(() {
        _latitude = result.latitude;
        _longitude = result.longitude;
        _gpsAccuracy = result.accuracy;
        _villageLocation = result.village;
        _locating = false;
      });
    } catch (e) {
      setState(() {
        _locError = 'Could not get location: $e';
        _locating = false;
      });
    }
  }

  Future<void> _openSettings() async {
    final result = await _locationService.getCurrentPosition();
    if (result.errorType == LocationErrorType.serviceDisabled) {
      await _locationService.openLocationSettings();
    } else {
      await _locationService.openAppSettings();
    }
  }

  @override
  void dispose() {
    _descController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildAppBar(),
            const StepIndicators(current: 1, total: 3),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _buildTypeBadge(),
                    const SizedBox(height: 16),
                    _buildDescSection(),
                    const SizedBox(height: 20),
                    _buildLocationSection(),
                    const SizedBox(height: 20),
                    _buildTagsSection(),
                    const SizedBox(height: 16),
                  ],
                ),
              ),
            ),
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
            child: Text('Report Details',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          ),
          const Text('Step 2 of 3',
              style: TextStyle(fontSize: 11, color: AppColors.muted)),
        ],
      ),
    );
  }

  Widget _buildTypeBadge() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
      decoration: BoxDecoration(
        color: AppColors.accent.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.accent.withValues(alpha: 0.25)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('📋', style: TextStyle(fontSize: 14)),
          const SizedBox(width: 6),
          Text(widget.incidentTypeName,
              style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppColors.accent)),
        ],
      ),
    );
  }

  Widget _buildDescSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Description',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        const Text('Describe what happened. Be specific and factual.',
            style: TextStyle(fontSize: 11, color: AppColors.muted)),
        const SizedBox(height: 8),
        TextField(
          controller: _descController,
          maxLines: 5,
          maxLength: 1000,
          style: const TextStyle(fontSize: 13, color: AppColors.text),
          decoration: InputDecoration(
            hintText: 'I noticed...',
            hintStyle: const TextStyle(color: AppColors.muted),
            filled: true,
            fillColor: AppColors.surface2,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: AppColors.border),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: AppColors.border),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: AppColors.accent),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildLocationSection() {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text('📍', style: TextStyle(fontSize: 16)),
              const SizedBox(width: 8),
              const Text('Location',
                  style:
                      TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
              const Spacer(),
              if (_locating)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: AppColors.accent),
                ),
              if (!_locating && _latitude != null)
                const StatusBadge(label: 'Acquired', type: BadgeType.ok),
              if (!_locating && _locError != null)
                GestureDetector(
                  onTap: _getLocation,
                  child: const StatusBadge(label: 'Retry', type: BadgeType.warn),
                ),
            ],
          ),
          const SizedBox(height: 8),
          if (_latitude != null) ...[
            if (_villageLocation != null) ...[
              Container(
                padding: const EdgeInsets.all(10),
                margin: const EdgeInsets.only(bottom: 8),
                decoration: BoxDecoration(
                  color: AppColors.accent.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: AppColors.accent.withValues(alpha: 0.2)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _locationRow('🏘️', 'Village', _villageLocation!.village),
                    const SizedBox(height: 4),
                    _locationRow('📍', 'Cell', _villageLocation!.cell),
                    const SizedBox(height: 4),
                    _locationRow('🗺️', 'Sector', _villageLocation!.sector),
                  ],
                ),
              ),
            ],
            Text(
              '${_latitude!.toStringAsFixed(6)}, ${_longitude!.toStringAsFixed(6)}',
              style: const TextStyle(
                  fontSize: 12,
                  fontFamily: 'monospace',
                  color: AppColors.accent),
            ),
            if (_gpsAccuracy != null)
              Text(
                'Accuracy: ±${_gpsAccuracy!.toStringAsFixed(1)}m',
                style:
                    const TextStyle(fontSize: 10, color: AppColors.muted),
              ),
          ] else if (_locError != null) ...[
            Text(_locError!,
                style: const TextStyle(
                    fontSize: 11, color: AppColors.danger)),
            const SizedBox(height: 8),
            Row(
              children: [
                if (_canOpenSettings)
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () async {
                        await _openSettings();
                        // Give user time to toggle settings, then retry
                        await Future.delayed(const Duration(seconds: 1));
                        _getLocation();
                      },
                      icon: const Icon(Icons.settings, size: 14),
                      label: const Text('Open Settings',
                          style: TextStyle(fontSize: 11)),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.accent,
                        side: const BorderSide(color: AppColors.accent),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(8)),
                        padding: const EdgeInsets.symmetric(
                            horizontal: 10, vertical: 6),
                      ),
                    ),
                  ),
                if (_canOpenSettings) const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _getLocation,
                    icon: const Icon(Icons.refresh, size: 14),
                    label: const Text('Retry',
                        style: TextStyle(fontSize: 11)),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.warn,
                      side: const BorderSide(color: AppColors.warn),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8)),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 6),
                    ),
                  ),
                ),
              ],
            ),
          ],
          if (_locating)
            const Text('Getting GPS coordinates...',
                style: TextStyle(fontSize: 11, color: AppColors.muted)),
        ],
      ),
    );
  }

  Widget _locationRow(String emoji, String label, String value) {
    return Row(
      children: [
        Text(emoji, style: const TextStyle(fontSize: 13)),
        const SizedBox(width: 6),
        Text('$label: ',
            style: const TextStyle(
                fontSize: 11, color: AppColors.muted, fontWeight: FontWeight.w500)),
        Expanded(
          child: Text(value,
              style: const TextStyle(
                  fontSize: 12, fontWeight: FontWeight.w600, color: AppColors.text)),
        ),
      ],
    );
  }

  Widget _buildTagsSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Contextual Tags',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        const Text('Select any that apply (optional)',
            style: TextStyle(fontSize: 11, color: AppColors.muted)),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: _tags.map((tag) {
            final sel = _selectedTags.contains(tag);
            return GestureDetector(
              onTap: () => setState(() {
                sel ? _selectedTags.remove(tag) : _selectedTags.add(tag);
              }),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                decoration: BoxDecoration(
                  color: sel
                      ? AppColors.accent.withValues(alpha: 0.12)
                      : AppColors.surface2,
                  border: Border.all(
                      color: sel
                          ? AppColors.accent
                          : AppColors.border),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  tag,
                  style: TextStyle(
                    fontSize: 12,
                    color: sel ? AppColors.accent : AppColors.muted,
                    fontWeight: sel ? FontWeight.w600 : FontWeight.normal,
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }

  Widget _buildContinueButton() {
    final hasDesc = _descController.text.trim().length >= 10;
    final hasLoc = _latitude != null;
    final enabled = hasDesc && hasLoc;
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 16),
      child: SizedBox(
        width: double.infinity,
        height: 50,
        child: ElevatedButton(
          onPressed: enabled
              ? () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => ReportStep3Screen(
                        incidentTypeId: widget.incidentTypeId,
                        incidentTypeName: widget.incidentTypeName,
                        description: _descController.text.trim(),
                        latitude: _latitude!,
                        longitude: _longitude!,
                        gpsAccuracy: _gpsAccuracy,
                        tags: List.from(_selectedTags),
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
