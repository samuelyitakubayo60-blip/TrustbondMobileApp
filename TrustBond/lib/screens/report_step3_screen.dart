import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:image/image.dart' as img;
import 'package:image_picker/image_picker.dart';
import 'package:exif/exif.dart';
import 'package:file_picker/file_picker.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import '../config/theme.dart';
import '../services/device_status_service.dart';
import '../services/motion_service.dart';
import '../services/mobile_verification_service.dart';
import '../services/app_refresh_bus.dart';
import '../services/leader_service.dart';
import '../services/offline_report_queue_service.dart';
import '../widgets/shared_widgets.dart';
import 'leader_inbox_screen.dart';
import 'report_success_screen.dart';

class ReportStep3Screen extends StatefulWidget {
  final int incidentTypeId;
  final String incidentTypeName;
  final String description;
  final double latitude;
  final double longitude;
  final double? gpsAccuracy;
  final List<String> tags;
  final bool localLeaderSubmit;

  const ReportStep3Screen({
    super.key,
    required this.incidentTypeId,
    required this.incidentTypeName,
    required this.description,
    required this.latitude,
    required this.longitude,
    this.gpsAccuracy,
    this.tags = const [],
    this.localLeaderSubmit = false,
  });

  @override
  State<ReportStep3Screen> createState() => _ReportStep3ScreenState();
}

class _ReportStep3ScreenState extends State<ReportStep3Screen> {
  final _picker = ImagePicker();
  final _audioRecorder = AudioRecorder();
  final _statusService = DeviceStatusService();
  final _queueService = OfflineReportQueueService();

  final List<_EvidenceFile> _files = [];
  bool _submitting = false;
  bool _submitted = false; // Prevents duplicate submissions after success
  String? _error;
  String? _submitStatus;
  bool _isRecording = false;
  Duration _recordingDuration = Duration.zero;
  Timer? _recordingTimer;

  @override
  void dispose() {
    _recordingTimer?.cancel();
    _audioRecorder.dispose();
    super.dispose();
  }

  Future<String> _sanitizePhotoPath(String sourcePath) async {
    try {
      // Skip processing for small files to improve performance
      final sourceFile = File(sourcePath);
      final fileSize = await sourceFile.length();
      
      // If file is already reasonably sized, skip processing
      if (fileSize < 2 * 1024 * 1024) { // Less than 2MB
        return sourcePath;
      }

      final sourceBytes = await sourceFile.readAsBytes();
      final decoded = img.decodeImage(sourceBytes);
      if (decoded == null) return sourcePath;

      // Only resize if image is too large
      if (decoded.width > 1920 || decoded.height > 1080) {
        // Resize to reasonable dimensions
        final resized = img.copyResize(decoded, width: 1920, height: 1080, maintainAspect: true);
        
        final dir = await getTemporaryDirectory();
        final sanitizedPath =
            '${dir.path}/tb_${DateTime.now().microsecondsSinceEpoch}.jpg';
        final sanitized = img.encodeJpg(resized, quality: 85);
        await File(sanitizedPath).writeAsBytes(sanitized, flush: true);
        return sanitizedPath;
      }

      // Just compress without resizing
      final dir = await getTemporaryDirectory();
      final sanitizedPath =
          '${dir.path}/tb_${DateTime.now().microsecondsSinceEpoch}.jpg';
      final sanitized = img.encodeJpg(decoded, quality: 90);
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
      await _validateAndAddEvidence(img.path, 'photo', false);
    }
  }

  Future<void> _pickAudio() async {
    // Request microphone permission
    final status = await Permission.microphone.request();
    if (!status.isGranted) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Microphone permission is required to record audio evidence.'),
          duration: Duration(seconds: 3),
        ),
      );
      return;
    }

    final hasPermission = await _audioRecorder.hasPermission();
    if (!hasPermission) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Microphone permission denied. Please enable it in settings.'),
          duration: Duration(seconds: 3),
        ),
      );
      return;
    }

    try {
      final dir = await getTemporaryDirectory();
      final path = '${dir.path}/tb_audio_${DateTime.now().millisecondsSinceEpoch}.m4a';
      await _audioRecorder.start(
        const RecordConfig(encoder: AudioEncoder.aacLc, bitRate: 64000),
        path: path,
      );
      setState(() {
        _isRecording = true;
        _recordingDuration = Duration.zero;
      });
      _recordingTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (_isRecording && mounted) {
          setState(() => _recordingDuration += const Duration(seconds: 1));
        }
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Failed to start recording: $e'),
          duration: const Duration(seconds: 3),
        ),
      );
    }
  }

  Future<void> _stopRecording() async {
    _recordingTimer?.cancel();
    _recordingTimer = null;
    try {
      final path = await _audioRecorder.stop();
      setState(() => _isRecording = false);
      if (path != null && path.isNotEmpty) {
        setState(() => _files.add(_EvidenceFile(path: path, type: 'audio', isLive: true)));
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Audio recorded (${_recordingDuration.inSeconds}s) ✓'),
              duration: const Duration(seconds: 2),
            ),
          );
        }
      }
    } catch (e) {
      setState(() => _isRecording = false);
    }
  }
  Future<void> _pickExistingAudio() async {
    try {
      final result = await FilePicker.pickFiles(
        type: FileType.audio,
      );
      if (result != null && result.files.single.path != null) {
        setState(() => _files.add(_EvidenceFile(path: result.files.single.path!, type: 'audio', isLive: false)));
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to pick audio: $e')),
      );
    }
  }

  Future<void> _validateAndAddEvidence(String filePath, String fileType, bool isLiveCapture) async {
    final file = File(filePath);
    final fileName = file.path.split('/').last.toLowerCase();
    
    final suspiciousPatterns = [
      'screenshot', 'screen_shot', 'capture', 'download', 'whatsapp', 
      'telegram', 'instagram', 'facebook', 'twitter', 'saved', 
      'copy', 'duplicate', 'forward', 'received', 'export'
    ];
    
    final hasSuspiciousName = suspiciousPatterns.any((pattern) => fileName.contains(pattern));
    
    DateTime? captureDate;
    if (fileType == 'photo') {
      try {
        final bytes = await file.readAsBytes();
        final tags = await readExifFromBytes(bytes);
        if (tags.containsKey('Image DateTime')) {
          final dateString = tags['Image DateTime']?.toString();
          if (dateString != null) {
            final formatted = dateString.replaceFirst(':', '-').replaceFirst(':', '-');
            captureDate = DateTime.tryParse(formatted);
          }
        } else if (tags.containsKey('EXIF DateTimeOriginal')) {
          final dateString = tags['EXIF DateTimeOriginal']?.toString();
          if (dateString != null) {
            final formatted = dateString.replaceFirst(':', '-').replaceFirst(':', '-');
            captureDate = DateTime.tryParse(formatted);
          }
        }
      } catch (_) {}
    }

    final stat = await file.stat();
    final now = DateTime.now();
    
    final actualCreationTime = captureDate ?? stat.accessed;
    final creationTimeDiff = now.difference(actualCreationTime);
    final isOldFile = creationTimeDiff.inHours > 24;
    
    String warningMessage = '';
    bool shouldBlock = false;
    
    if (hasSuspiciousName) {
      warningMessage = 'This file appears to be from another app or was downloaded. For evidence integrity, please use original photos/videos taken with your camera.';
      shouldBlock = true;
    } else if (isOldFile && !isLiveCapture) {
      warningMessage = 'This evidence was captured over 24 hours ago. For best evidence quality, original recent camera captures are preferred.';
      shouldBlock = false;
    } else if (!isLiveCapture && captureDate == null && fileType == 'photo') {
      warningMessage = 'Could not verify original capture date from metadata. Gallery items may have reduced authenticity.';
      shouldBlock = false;
    }

    if (warningMessage.isNotEmpty) {
      if (!mounted) return;
      showDialog(
        context: context,
        builder: (BuildContext context) {
          return AlertDialog(
            title: Row(
              children: [
                Icon(shouldBlock ? Icons.warning_amber_rounded : Icons.info_outline,
                    size: 18, color: shouldBlock ? AppColors.warn : AppColors.accent),
                const SizedBox(width: 8),
                Text(shouldBlock ? 'Evidence Validation Alert' : 'Evidence Quality Notice', style: const TextStyle(fontSize: 14)),
              ],
            ),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(warningMessage),
                const SizedBox(height: 12),
                if (!shouldBlock) ...[
                  const Text('You can still submit this evidence, but original captures provide stronger verification.', 
                       style: TextStyle(fontSize: 12, color: AppColors.muted)),
                ],
              ],
            ),
            actions: [
              if (!shouldBlock) ...[
                TextButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('Cancel'),
                ),
                TextButton(
                  onPressed: () {
                    Navigator.of(context).pop();
                    _addEvidenceFile(filePath, fileType, isLiveCapture);
                  },
                  child: const Text('Use Anyway'),
                ),
              ] else ...[
                TextButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('I Understand'),
                ),
              ],
            ],
          );
        },
      );
    } else {
      _addEvidenceFile(filePath, fileType, isLiveCapture);
    }
  }

  void _addEvidenceFile(String filePath, String fileType, bool isLiveCapture) async {
    final sanitizedPath = await _sanitizePhotoPath(filePath);
    setState(() => _files
        .add(_EvidenceFile(path: sanitizedPath, type: fileType, isLive: isLiveCapture)));
  }

  void _removeFile(int index) {
    setState(() => _files.removeAt(index));
  }

  Future<void> _submit() async {
    if (_submitted) return; // Already submitted successfully — block duplicate
    final networkType = await _statusService.getNetworkType();
    final isOffline = (networkType ?? '').toLowerCase() == 'none' ||
        (networkType ?? '').toLowerCase() == 'offline' ||
        (networkType ?? '').trim().isEmpty;
    setState(() {
      _submitting = true;
      _error = null;
      _submitStatus = isOffline
          ? 'No internet detected. Saving offline and retrying...'
          : 'Submitting online...';
    });

    try {
      final verificationService = MobileVerificationService();
      final evidenceFiles = _files.map((file) => File(file.path)).toList(growable: false);
      final evidenceMetadata = _files
          .map((file) => {
                'mediaLatitude': widget.latitude,
                'mediaLongitude': widget.longitude,
                'capturedAt': DateTime.now().toIso8601String(),
                'isLiveCapture': file.isLive,
              })
          .toList(growable: false);

      final mobileVerification = await verificationService.verifyReport(
        reportLocation: Position(
          longitude: widget.longitude,
          latitude: widget.latitude,
          timestamp: DateTime.now(),
          accuracy: widget.gpsAccuracy ?? 0,
          altitude: 0,
          altitudeAccuracy: 0,
          heading: 0,
          headingAccuracy: 0,
          speed: 0,
          speedAccuracy: 0,
        ),
        evidenceFiles: evidenceFiles,
        evidenceMetadata: evidenceMetadata,
      );

      // Hard block only on confirmed tampering or non-original source.
      // A 'warning' (e.g. gallery photo) is allowed through — the backend
      // will down-weight the trust score but must not silently drop the report.
      if (mobileVerification.status == 'failed') {
        String errorMessage = "Cannot submit report: ";
        if (!mobileVerification.evidenceSourceValid) {
          errorMessage +=
              "Evidence appears to be downloaded or not original. Please use original photos/videos taken at the scene.";
        } else if (mobileVerification.evidenceTamperingDetected) {
          errorMessage +=
              "Evidence appears to be a screenshot or screen recording. Please use original photos/videos taken at the scene.";
        } else {
          errorMessage += "Evidence failed verification. Please use original photos/videos taken at the scene.";
        }
        setState(() {
          _error = errorMessage;
          _submitting = false;
        });
        return;
      }

      // Show a non-blocking warning for 'warning' status (e.g. gallery items).
      if (mobileVerification.status == 'warning' && mounted) {
        setState(() {
          _error = "Evidence quality warning: original live captures are preferred. Your report will be submitted with a lower trust score.";
        });
      }

      MotionSample motion;
      try {
        motion = await collectMotionSample().timeout(const Duration(milliseconds: 800));
      } catch (_) {
        motion = MotionSample(
            motionLevel: 'low', movementSpeed: 0.0, wasStationary: true);
      }

      final batteryLevel = await _statusService
          .getBatteryLevel()
          .timeout(const Duration(milliseconds: 500), onTimeout: () => null);

      final leaderTok = await LeaderService().getAccessTokenForSubmission();
      final submitAsLeader =
          widget.localLeaderSubmit || (leaderTok != null && leaderTok.isNotEmpty);

      if (widget.localLeaderSubmit && (leaderTok == null || leaderTok.isEmpty)) {
        setState(() {
          _error =
              'Local leader session expired. Open Profile → Local Leader and sign in again.';
          _submitting = false;
        });
        return;
      }

      final result = await _queueService.submitReport(
        incidentTypeId: widget.incidentTypeId,
        incidentTypeName: widget.incidentTypeName,
        description: widget.description,
        latitude: widget.latitude,
        longitude: widget.longitude,
        gpsAccuracy: widget.gpsAccuracy,
        evidenceFiles: evidenceFiles,
        isLiveCapture: _files.map((file) => file.isLive).toList(growable: false),
        contextTags: widget.tags,
        motionLevel: motion.motionLevel,
        movementSpeed: motion.movementSpeed,
        wasStationary: motion.wasStationary,
        batteryLevel: batteryLevel,
        mobileRuleStatus: mobileVerification.status,
        mobileRuleDetails: mobileVerification.details,
        locationConsistencyCheck: mobileVerification.locationConsistencyCheck,
        evidenceSourceValid: mobileVerification.evidenceSourceValid,
        evidenceTamperingDetected: mobileVerification.evidenceTamperingDetected,
        leaderAccessToken: leaderTok,
      );

      _submitted = true; // Mark as submitted to prevent duplicates
      AppRefreshBus.notify('report_submitted');

      if (mounted) {
        if (result.queuedOffline) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text("Saved. Will send automatically when you're back online."),
              duration: Duration(seconds: 2),
            ),
          );
        }

        if (submitAsLeader) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Incident submitted as local leader.'),
              duration: Duration(seconds: 2),
            ),
          );
          Navigator.of(context).pushAndRemoveUntil(
            MaterialPageRoute(builder: (_) => const LeaderInboxScreen()),
            (route) => route.isFirst,
          );
          return;
        }

        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(
            builder: (_) => ReportSuccessScreen(
              reportId: result.reportId,
              incidentTypeName: widget.incidentTypeName,
              queuedOffline: result.queuedOffline,
              queuedMessage: result.queuedOffline
                  ? "Saved. Will send automatically when you're back online."
                  : null,
            ),
          ),
          (route) => route.isFirst,
        );
      }
    } catch (e) {
      String errorMsg = e.toString();
      // User-friendly messages for duplicate/rate-limit rejections
      if (errorMsg.contains('409') || errorMsg.toLowerCase().contains('duplicate')) {
        errorMsg = 'This incident was already submitted recently. Please wait before reporting the same incident again.';
      } else if (errorMsg.contains('429') || errorMsg.toLowerCase().contains('rate limit')) {
        errorMsg = 'Too many reports in a short time. Please wait a moment before submitting again.';
      } else {
        errorMsg = 'Failed to submit report: $errorMsg';
      }
      setState(() {
        _error = errorMsg;
        _submitStatus = null;
      });
    } finally {
      if (mounted) {
        setState(() {
          _submitting = false;
          _submitStatus = null;
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
                        'Photos, videos, and audio strengthen report credibility',
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
            if (_submitStatus != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 6),
                child: Row(
                  children: [
                    Icon(
                      _submitStatus!.toLowerCase().contains('online')
                          ? Icons.wifi
                          : Icons.cloud_off,
                      size: 14,
                      color: AppColors.muted,
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        _submitStatus!,
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.muted,
                        ),
                      ),
                    ),
                  ],
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
          const Text('Take photos, record videos, or choose from gallery (smart validation enabled)',
              style: TextStyle(fontSize: 11, color: AppColors.muted),
              textAlign: TextAlign.center),
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final spacing = 8.0;
              final itemWidth = (constraints.maxWidth - spacing) / 2;
              final chips = <Widget>[
                SizedBox(
                  width: itemWidth,
                  child: _actionChip('Photo', _pickPhoto, icon: Icons.camera_alt_outlined),
                ),
                SizedBox(
                  width: itemWidth,
                  child: _actionChip('Video', _pickVideo, icon: Icons.videocam_outlined),
                ),
                if (!Platform.isWindows)
                  SizedBox(
                    width: itemWidth,
                    child: _actionChip(
                      _isRecording
                          ? 'Stop ${_recordingDuration.inSeconds}s'
                          : 'Record Audio',
                      _isRecording ? _stopRecording : _pickAudio,
                      icon: _isRecording ? Icons.stop_circle_outlined : Icons.mic_outlined,
                      highlight: _isRecording,
                    ),
                  ),
                SizedBox(
                  width: itemWidth,
                  child: _actionChip('Gallery Audio', _pickExistingAudio, icon: Icons.audio_file_outlined),
                ),
                SizedBox(
                  width: itemWidth,
                  child: _actionChip('Gallery Photos', _pickGallery, icon: Icons.photo_library_outlined),
                ),
              ];
              return Wrap(
                spacing: spacing,
                runSpacing: spacing,
                children: chips,
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _actionChip(String label, Future<void> Function() onTap, {IconData? icon, bool highlight = false}) {
    final chipColor = highlight ? AppColors.danger : AppColors.accent;
    return Material(
      color: highlight ? AppColors.danger.withValues(alpha: 0.08) : AppColors.surface2,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () {
          unawaited(onTap());
        },
        child: Container(
          height: 44,
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            border: Border.all(color: highlight ? AppColors.danger.withValues(alpha: 0.5) : AppColors.border),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (icon != null) ...[
                Icon(icon, size: 14, color: chipColor),
                const SizedBox(width: 4),
              ],
              Text(
                label,
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: highlight ? chipColor : AppColors.text),
              ),
            ],
          ),
        ),
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
                      : f.type == 'video'
                          ? Container(
                              width: 44,
                              height: 44,
                              color: AppColors.surface3,
                              child: const Icon(Icons.videocam,
                                  color: AppColors.accent2, size: 22),
                            )
                          : Container(
                              width: 44,
                              height: 44,
                              color: AppColors.surface3,
                              child: const Icon(Icons.mic,
                                  color: AppColors.accent, size: 22),
                            ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        f.type == 'photo' ? 'Photo' : f.type == 'video' ? 'Video' : 'Audio',
                        style: const TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w600),
                      ),
                      Text(
                        f.isLive ? 'Live capture ✓' : f.type == 'audio' ? 'Audio recording' : 'From gallery',
                        style: TextStyle(
                          fontSize: 10,
                          color: f.isLive || f.type == 'audio'
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
              Icon(Icons.smart_toy_outlined, size: 14, color: AppColors.accent),
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
              ? Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: AppColors.bg,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      _submitStatus?.toLowerCase().contains('online') == true
                          ? 'Submitting online...'
                          : 'Saving offline...',
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 14,
                      ),
                    ),
                  ],
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
