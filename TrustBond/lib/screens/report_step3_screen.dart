import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../services/api_service.dart';
import '../services/device_service.dart';
import '../services/motion_service.dart';
import '../services/device_status_service.dart';
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
  final _apiService = ApiService();
  final _deviceService = DeviceService();
  final _picker = ImagePicker();
  final _statusService = DeviceStatusService();

  final List<_EvidenceFile> _files = [];
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    super.dispose();
  }

  Future<void> _pickPhoto() async {
    final img = await _picker.pickImage(
        source: ImageSource.camera, imageQuality: 80);
    if (img != null) {
      setState(() => _files
          .add(_EvidenceFile(path: img.path, type: 'photo', isLive: true)));
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
      setState(() => _files
          .add(_EvidenceFile(path: img.path, type: 'photo', isLive: false)));
    }
  }

  void _removeFile(int index) {
    setState(() => _files.removeAt(index));
  }

  Future<void> _submit() async {
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      String? deviceId = await _deviceService.getDeviceId();
      final deviceHash = await _deviceService.getDeviceHash();

      // Auto-register to get device_id when possible; backend can also resolve by device_hash
      if (deviceId == null || deviceId.isEmpty) {
        try {
          final regResult = await _apiService.registerDevice(deviceHash);
          deviceId = regResult['device_id']?.toString();
          if (deviceId != null && deviceId.isNotEmpty) {
            await _deviceService.saveDeviceId(deviceId);
          }
        } catch (_) {
          // Continue: submit with device_hash only; backend will find-or-create device
        }
      }

      // Collect motion/sensor data before submit (non-blocking)
      MotionSample motion;
      try {
        motion = await collectMotionSample();
      } catch (_) {
        motion = MotionSample(
            motionLevel: 'low', movementSpeed: 0.0, wasStationary: true);
      }

      // Collect network and battery status (best-effort; failures are not fatal)
      final networkType = await _statusService.getNetworkType();
      final batteryLevel = await _statusService.getBatteryLevel();

      // Always send device_hash so backend can find-or-create device (fixes "Device not found")
      final reportData = <String, dynamic>{
        'device_hash': deviceHash,
        'incident_type_id': widget.incidentTypeId,
        'description': widget.description,
        'latitude': widget.latitude,
        'longitude': widget.longitude,
      };
      if (deviceId != null && deviceId.isNotEmpty) {
        reportData['device_id'] = deviceId;
      }
      // Only send optional fields if they have values
      if (widget.gpsAccuracy != null) {
        reportData['gps_accuracy'] = widget.gpsAccuracy;
      }
      reportData['motion_level'] = motion.motionLevel;
      if (motion.movementSpeed != null &&
          motion.movementSpeed!.isFinite) {
        reportData['movement_speed'] = motion.movementSpeed;
      }
      reportData['was_stationary'] = motion.wasStationary;
      // Contextual tags from Step 2 (e.g. Night-time, Weapons involved)
      reportData['context_tags'] = widget.tags;
      // Client metadata
      reportData['app_version'] = '1.0.0'; // later can be from package_info_plus
      if (networkType != null) {
        reportData['network_type'] = networkType;
      }
      if (batteryLevel != null) {
        reportData['battery_level'] = batteryLevel;
      }

      Map<String, dynamic> result;
      try {
        result = await _apiService.submitReport(reportData);
      } catch (e) {
        final msg = e.toString();
        if (msg.contains('Device not found') && deviceId != null && deviceId.isNotEmpty) {
          await _deviceService.saveDeviceId(''); // clear stale id
          reportData.remove('device_id');
          result = await _apiService.submitReport(reportData);
          deviceId = result['device_id']?.toString();
          if (deviceId != null && deviceId.isNotEmpty) {
            await _deviceService.saveDeviceId(deviceId);
          }
        } else {
          rethrow;
        }
      }
      final reportId = result['report_id']?.toString() ?? '';
      if (deviceId == null || deviceId.isEmpty) {
        deviceId = result['device_id']?.toString();
        if (deviceId != null && deviceId.isNotEmpty) {
          await _deviceService.saveDeviceId(deviceId);
        }
      }

      // Upload evidence files with verification feedback
      final List<String> uploadErrors = [];
      for (int i = 0; i < _files.length; i++) {
        final f = _files[i];
        try {
          final evidenceResult = await _apiService.uploadEvidence(
            reportId,
            deviceId ?? '',
            f.path,
            mediaLatitude: widget.latitude,
            mediaLongitude: widget.longitude,
            capturedAt: DateTime.now(),
            isLiveCapture: f.isLive,
          );
          // Log verification status from backend
          final status = evidenceResult['verification_status'] ?? 'unknown';
          if (status == 'flagged') {
            uploadErrors.add('File ${i + 1}: flagged for review');
          }
        } catch (e) {
          uploadErrors.add('File ${i + 1}: ${e.toString()}');
        }
      }

      if (mounted) {
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(
              builder: (_) => ReportSuccessScreen(
                    reportId: reportId,
                    incidentTypeName: widget.incidentTypeName,
                    evidenceWarnings: uploadErrors,
                  )),
          (route) => route.isFirst,
        );
      }
    } catch (e) {
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _submitting = false;
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
          _preCheckRow('Description', widget.description.length >= 10,
              '${widget.description.length} chars'),
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
              : const Text('Submit Report',
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
