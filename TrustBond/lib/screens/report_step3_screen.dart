import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:image/image.dart' as img;
import 'package:path_provider/path_provider.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../services/api_service.dart';
import '../services/offline_report_queue.dart';
import '../services/offline_integration_guide.dart';
import '../services/device_service.dart';
import '../services/motion_service.dart';
import '../services/device_status_service.dart';
import '../services/app_refresh_bus.dart';
import '../models/report_model.dart';
import 'report_success_screen.dart';

class ReportStep3Screen extends StatefulWidget {
  final int incidentTypeId;
  final String incidentTypeName;
  final String description;
  final double latitude;
  final double longitude;
  final double? gpsAccuracy;
  final List<String> tags;

  const ReportStep3Screen({
    super.key,
    required this.incidentTypeId,
    required this.incidentTypeName,
    required this.description,
    required this.latitude,
    required this.longitude,
    this.gpsAccuracy,
    this.tags = const [],
  });

  @override
  State<ReportStep3Screen> createState() => _ReportStep3ScreenState();
}

class _ReportStep3ScreenState extends State<ReportStep3Screen> {
  static const Duration _foregroundBudget = Duration(seconds: 5);
  final _apiService = ApiService();
  final _deviceService = DeviceService();
  final _picker = ImagePicker();
  final _statusService = DeviceStatusService();
  final _offlineIntegration = OfflineReportingIntegration();

  final List<_EvidenceFile> _files = [];
  bool _submitting = false;
  String? _error;

  bool _isNetworkError(Object e) {
    return e is SocketException || e is TimeoutException;
  }

  @override
  void dispose() {
    super.dispose();
  }

  Future<String> _sanitizePhotoPath(String sourcePath) async {
    try {
      final sourceBytes = await File(sourcePath).readAsBytes();
      final decoded = img.decodeImage(sourceBytes);
      if (decoded == null) return sourcePath;

      final dir = await getTemporaryDirectory();
      final sanitizedPath =
          '${dir.path}/tb_${DateTime.now().microsecondsSinceEpoch}.jpg';
      final sanitized = img.encodeJpg(decoded, quality: 88);
      await File(sanitizedPath).writeAsBytes(sanitized, flush: true);
      return sanitizedPath;
    } catch (_) {
      return sourcePath;
    }
  }

  Future<void> _pickPhoto() async {
    final img = await _picker.pickImage(
        source: ImageSource.camera, imageQuality: 80);
    if (img != null) {
      final sanitizedPath = await _sanitizePhotoPath(img.path);
      setState(() => _files
          .add(_EvidenceFile(path: sanitizedPath, type: 'photo', isLive: true)));
    }
  }

  Future<void> _pickVideo() async {
    final vid = await _picker.pickVideo(
        source: ImageSource.camera, maxDuration: const Duration(seconds: 30));
    if (vid != null) {
      setState(() => _files
          .add(_EvidenceFile(path: vid.path, type: 'video', isLive: true)));
    }
  }

  Future<void> _pickGallery() async {
    final img = await _picker.pickImage(source: ImageSource.gallery);
    if (img != null) {
      final sanitizedPath = await _sanitizePhotoPath(img.path);
      setState(() => _files
          .add(_EvidenceFile(path: sanitizedPath, type: 'photo', isLive: false)));
    }
  }

  void _removeFile(int index) {
    setState(() => _files.removeAt(index));
  }

  bool _looksLikeServer500(Object e) {
    final msg = e.toString().toLowerCase();
    return msg.contains('http 500') ||
        msg.contains('(500)') ||
        msg.contains('status 500') ||
        msg.contains('internal server error');
  }

  String _toUserSafeError(Object e) {
    var msg = e.toString().replaceFirst('Exception: ', '').trim();
    msg = msg.replaceAll(RegExp(r'\s*\(HTTP\s*\d+\)\s*', caseSensitive: false), ' ').trim();
    msg = msg.replaceAll(RegExp(r'\s+'), ' ');
    return msg;
  }

  Future<ReportListItem?> _recoverReportAfterServerError({
    required String? deviceId,
    required String deviceHash,
    required Map<String, dynamic> reportData,
  }) async {
    String? resolvedDeviceId = deviceId;
    if (resolvedDeviceId == null || resolvedDeviceId.isEmpty) {
      try {
        final reg = await _apiService
            .registerDevice(deviceHash)
            .timeout(const Duration(seconds: 2));
        resolvedDeviceId = reg['device_id']?.toString();
        if (resolvedDeviceId != null && resolvedDeviceId.isNotEmpty) {
          await _deviceService.saveDeviceId(resolvedDeviceId);
        }
      } catch (_) {}
    }

    if (resolvedDeviceId == null || resolvedDeviceId.isEmpty) {
      return null;
    }

    final list = await _apiService
        .getMyReports(resolvedDeviceId)
        .timeout(const Duration(seconds: 8));
    final reports = list
        .map((e) => ReportListItem.fromJson(e as Map<String, dynamic>))
        .toList(growable: false)
      ..sort((a, b) => b.reportedAt.compareTo(a.reportedAt));

    final now = DateTime.now();
    final expectedType = reportData['incident_type_id'] as int?;
    final expectedDesc = ((reportData['description'] ?? '') as String).trim();
    final expectedLat = (reportData['latitude'] as num?)?.toDouble();
    final expectedLng = (reportData['longitude'] as num?)?.toDouble();

    for (final r in reports.take(15)) {
      if (now.difference(r.reportedAt).inMinutes > 10) continue;
      if (expectedType != null && r.incidentTypeId != expectedType) continue;
      final desc = (r.description ?? '').trim();
      if (expectedDesc.isNotEmpty && desc != expectedDesc) continue;
      if (expectedLat != null && (r.latitude - expectedLat).abs() > 0.0005) continue;
      if (expectedLng != null && (r.longitude - expectedLng).abs() > 0.0005) continue;
      return r;
    }
    return null;
  }

  Future<void> _submit() async {
    setState(() {
      _submitting = true;
      _error = null;
    });
    
    try {
      final deviceHash = await _deviceService.getDeviceHash();

      // Collect motion/sensor data before submit (non-blocking)
      MotionSample motion;
      try {
        motion = await collectMotionSample().timeout(const Duration(milliseconds: 800));
      } catch (_) {
        motion = MotionSample(
            motionLevel: 'low', movementSpeed: 0.0, wasStationary: true);
      }

      // Collect network and battery status (best-effort; failures are not fatal)
      final networkType = await _statusService
          .getNetworkType()
          .timeout(const Duration(milliseconds: 500), onTimeout: () => null);
      final batteryLevel = await _statusService
          .getBatteryLevel()
          .timeout(const Duration(milliseconds: 500), onTimeout: () => null);

      // Prepare evidence files
      final evidenceFiles = _files.map((f) => File(f.path)).toList();

      // Submit using enhanced offline-first API
      final queueId = await _offlineIntegration.submitReportOffline(
        deviceHash: deviceHash,
        incidentTypeId: widget.incidentTypeId,
        description: widget.description,
        latitude: widget.latitude,
        longitude: widget.longitude,
        evidenceFiles: evidenceFiles,
        gpsAccuracy: widget.gpsAccuracy,
        movementSpeed: motion.movementSpeed,
        wasStationary: motion.wasStationary,
        networkType: networkType,
        batteryLevel: batteryLevel,
        motionLevel: motion.motionLevel,
        contextTags: widget.tags,
      );

      AppRefreshBus.notify('report_submitted');
      
      if (mounted) {
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(
            builder: (_) => ReportSuccessScreen(
              reportId: queueId,
              incidentTypeName: widget.incidentTypeName,
              evidenceWarnings: const [],
              queuedOffline: true,
              queuedIsLocal: true,
              queuedMessage:
                  'Report submitted successfully. It will sync automatically when connection is available.',
            ),
          ),
          (route) => route.isFirst,
        );
      }
      
    } catch (e) {
      setState(() {
        _error = 'Failed to submit report: ${e.toString()}';
      });
    } finally {
      if (mounted) {
        setState(() {
          _submitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildAppBar(),
            const StepIndicators(current: 2, total: 3),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Add Evidence',
                        style: TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 4),
                    const Text(
                        'Photos and videos strengthen report credibility',
                        style:
                            TextStyle(fontSize: 12, color: AppColors.muted)),
                    const SizedBox(height: 16),
                    _buildUploadArea(),
                    if (_files.isNotEmpty) ...[
                      const SizedBox(height: 16),
                      _buildFileList(),
                    ],
                    const SizedBox(height: 20),
                    _buildPreCheckCard(),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      _buildError(),
                    ],
                    const SizedBox(height: 16),
                  ],
                ),
              ),
            ),
            _buildSubmitButton(),
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
            child: Text('Evidence',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          ),
          const Text('Step 3 of 3',
              style: TextStyle(fontSize: 11, color: AppColors.muted)),
        ],
      ),
    );
  }

  Widget _buildUploadArea() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(
            color: AppColors.accent.withValues(alpha: 0.2),
            style: BorderStyle.solid),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        children: [
          Icon(Icons.cloud_upload_outlined,
              size: 38,
              color: AppColors.accent.withValues(alpha: 0.6)),
          const SizedBox(height: 8),
          const Text('Upload Evidence',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          const Text('Take a photo, record video, or choose from gallery',
              style: TextStyle(fontSize: 11, color: AppColors.muted),
              textAlign: TextAlign.center),
          const SizedBox(height: 14),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _actionChip('📷 Photo', _pickPhoto),
              const SizedBox(width: 8),
              _actionChip('🎥 Video', _pickVideo),
              const SizedBox(width: 8),
              _actionChip('🖼️ Gallery', _pickGallery),
            ],
          ),
        ],
      ),
    );
  }

  Widget _actionChip(String label, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: AppColors.surface2,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(label,
            style: const TextStyle(fontSize: 12, color: AppColors.text)),
      ),
    );
  }

  Widget _buildFileList() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('${_files.length} file${_files.length > 1 ? 's' : ''} attached',
            style:
                const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        ...List.generate(_files.length, (i) {
          final f = _files[i];
          return Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AppColors.surface2,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.border),
            ),
            child: Row(
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: f.type == 'photo'
                      ? Image.file(File(f.path),
                          width: 44, height: 44, fit: BoxFit.cover)
                      : Container(
                          width: 44,
                          height: 44,
                          color: AppColors.surface3,
                          child: const Icon(Icons.videocam,
                              color: AppColors.accent2, size: 22),
                        ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        f.type == 'photo' ? 'Photo' : 'Video',
                        style: const TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w600),
                      ),
                      Text(
                        f.isLive ? 'Live capture ✓' : 'From gallery',
                        style: TextStyle(
                          fontSize: 10,
                          color: f.isLive
                              ? AppColors.accent
                              : AppColors.muted,
                        ),
                      ),
                    ],
                  ),
                ),
                GestureDetector(
                  onTap: () => _removeFile(i),
                  child: const Icon(Icons.close,
                      size: 18, color: AppColors.muted),
                ),
              ],
            ),
          );
        }),
      ],
    );
  }

  Widget _buildPreCheckCard() {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.accent.withValues(alpha: 0.05),
        border: Border.all(color: AppColors.accent.withValues(alpha: 0.15)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Text('🤖', style: TextStyle(fontSize: 14)),
              SizedBox(width: 6),
              Text('AI Pre-Check',
                  style:
                      TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
            ],
          ),
          const SizedBox(height: 8),
          _preCheckRow('GPS Location', widget.latitude != 0, 'Acquired'),
          _preCheckRow(
              'Evidence', _files.isNotEmpty, '${_files.length} files'),
          _preCheckRow('Live Capture', _files.any((f) => f.isLive),
              _files.any((f) => f.isLive) ? 'Yes' : 'No'),
            _preCheckRow(
              'Description', true, widget.description.isEmpty ? 'Optional' : 'Added'),
        ],
      ),
    );
  }

  Widget _preCheckRow(String label, bool ok, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Icon(
            ok ? Icons.check_circle : Icons.radio_button_unchecked,
            size: 14,
            color: ok ? AppColors.accent : AppColors.muted,
          ),
          const SizedBox(width: 8),
          Expanded(
            child:
                Text(label, style: const TextStyle(fontSize: 11, color: AppColors.muted)),
          ),
          Text(value,
              style: TextStyle(
                  fontSize: 11,
                  color: ok ? AppColors.accent : AppColors.muted)),
        ],
      ),
    );
  }

  Widget _buildError() {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.danger.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.danger.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, size: 16, color: AppColors.danger),
          const SizedBox(width: 8),
          Expanded(
            child: Text(_error!,
                style: const TextStyle(
                    fontSize: 12, color: AppColors.danger)),
          ),
        ],
      ),
    );
  }

  Widget _buildSubmitButton() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 16),
      child: SizedBox(
        width: double.infinity,
        height: 50,
        child: ElevatedButton(
          onPressed: _submitting ? null : _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.accent,
            foregroundColor: AppColors.bg,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14)),
          ),
          child: _submitting
              ? const SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: AppColors.bg),
                )
              : const Text('Submit Anonymously',
                  style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
        ),
      ),
    );
  }
}

class _EvidenceFile {
  final String path;
  final String type;
  final bool isLive;

  _EvidenceFile({
    required this.path,
    required this.type,
    required this.isLive,
  });
}
