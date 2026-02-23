import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show defaultTargetPlatform, TargetPlatform, kIsWeb;
import 'package:image_picker/image_picker.dart';
import 'package:geolocator/geolocator.dart';
import '../services/api_service.dart';
import '../services/device_service.dart';
import '../models/report_model.dart';
import '../config/api_config.dart';

class MyReportsScreen extends StatefulWidget {
  const MyReportsScreen({super.key});

  @override
  State<MyReportsScreen> createState() => _MyReportsScreenState();
}

class _MyReportsScreenState extends State<MyReportsScreen> {
  final _apiService = ApiService();
  final _deviceService = DeviceService();

  String? _deviceId;
  List<ReportListItem> _reports = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadDeviceAndReports();
  }

  Future<void> _loadDeviceAndReports() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final deviceId = await _deviceService.getDeviceId();
    if (deviceId == null || deviceId.isEmpty) {
      setState(() {
        _deviceId = null;
        _reports = [];
        _loading = false;
        _error = 'No device registered. Submit a report first to register.';
      });
      return;
    }
    setState(() {
      _deviceId = deviceId;
    });
    try {
      final list = await _apiService.getMyReports(deviceId);
      setState(() {
        _reports = list
            .map((e) => ReportListItem.fromJson(e as Map<String, dynamic>))
            .toList();
        _loading = false;
        _error = null;
      });
    } catch (e) {
      setState(() {
        _reports = [];
        _loading = false;
        _error = e.toString().replaceFirst('Exception: ', '');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!_loading)
            Padding(
              padding: const EdgeInsets.only(right: 8.0, top: 8.0),
              child: Align(
                alignment: Alignment.centerRight,
                child: IconButton(
                  icon: const Icon(Icons.refresh),
                  onPressed: _loadDeviceAndReports,
                ),
              ),
            ),
          Expanded(child: _buildBody()),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.info_outline, size: 48, color: Colors.grey[600]),
              const SizedBox(height: 16),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.grey[700], fontSize: 16),
              ),
            ],
          ),
        ),
      );
    }
    if (_reports.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.assignment_outlined, size: 64, color: Colors.grey[400]),
              const SizedBox(height: 16),
              Text(
                'No reports yet',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      color: Colors.grey[600],
                    ),
              ),
              const SizedBox(height: 8),
              Text(
                'Submit a report from the Report tab to see it here.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.grey[600]),
              ),
            ],
          ),
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _loadDeviceAndReports,
      child: ListView.builder(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
        itemCount: _reports.length,
        itemBuilder: (context, index) {
          final report = _reports[index];
          return _ReportCard(
            report: report,
            onTap: () => _openDetail(report),
          );
        },
      ),
    );
  }

  void _openDetail(ReportListItem report) {
    if (_deviceId == null) return;
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (context) => _ReportDetailScreen(
          reportId: report.reportId,
          deviceId: _deviceId!,
          apiService: _apiService,
        ),
      ),
    );
  }
}

class _ReportCard extends StatelessWidget {
  final ReportListItem report;
  final VoidCallback onTap;

  const _ReportCard({required this.report, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final statusColor = _statusColor(report.ruleStatus);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      report.incidentTypeName ?? 'Incident #${report.incidentTypeId}',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: statusColor.withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      report.ruleStatus,
                      style: TextStyle(
                        color: statusColor,
                        fontWeight: FontWeight.w500,
                        fontSize: 12,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                _formatDate(report.reportedAt),
                style: TextStyle(
                  color: Colors.grey[600],
                  fontSize: 13,
                ),
              ),
              if (report.description != null && report.description!.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  report.description!.length > 120
                      ? '${report.description!.substring(0, 120)}...'
                      : report.description!,
                  style: TextStyle(color: Colors.grey[700], fontSize: 14),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  static Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'passed':
        return Colors.green;
      case 'flagged':
        return Colors.orange;
      case 'rejected':
        return Colors.red;
      default:
        return Colors.blue;
    }
  }

  static String _formatDate(DateTime d) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final reportDay = DateTime(d.year, d.month, d.day);
    if (reportDay == today) {
      return 'Today ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
    }
    final yesterday = today.subtract(const Duration(days: 1));
    if (reportDay == yesterday) {
      return 'Yesterday ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
    }
    return '${d.day}/${d.month}/${d.year} ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
  }
}

class _ReportDetailScreen extends StatefulWidget {
  final String reportId;
  final String deviceId;
  final ApiService apiService;

  const _ReportDetailScreen({
    required this.reportId,
    required this.deviceId,
    required this.apiService,
  });

  @override
  State<_ReportDetailScreen> createState() => _ReportDetailScreenState();
}

bool get _isMobileWithCamera =>
    !kIsWeb &&
    (defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS);

class _ReportDetailScreenState extends State<_ReportDetailScreen> {
  ReportDetailItem? _report;
  bool _loading = true;
  String? _error;
  bool _uploadingEvidence = false;
  final ImagePicker _picker = ImagePicker();

  @override
  void initState() {
    super.initState();
    _loadReport();
  }

  Future<void> _loadReport() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await widget.apiService.getReport(widget.reportId, widget.deviceId);
      if (!mounted) return;
      setState(() {
        _report = ReportDetailItem.fromJson(data);
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _loading = false;
      });
    }
  }

  void _showAddEvidenceOptions() {
    showModalBottomSheet<void>(
      context: context,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'Add evidence',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 16),
              if (_isMobileWithCamera)
                ListTile(
                  leading: const Icon(Icons.camera_alt),
                  title: const Text('Take photo'),
                  onTap: () {
                    Navigator.pop(context);
                    _pickAndUploadEvidence(isVideo: false, fromCamera: true);
                  },
                ),
              ListTile(
                leading: const Icon(Icons.photo_library),
                title: const Text('Choose photo'),
                onTap: () {
                  Navigator.pop(context);
                  _pickAndUploadEvidence(isVideo: false, fromCamera: false);
                },
              ),
              if (_isMobileWithCamera)
                ListTile(
                  leading: const Icon(Icons.videocam),
                  title: const Text('Record video'),
                  onTap: () {
                    Navigator.pop(context);
                    _pickAndUploadEvidence(isVideo: true, fromCamera: true);
                  },
                ),
              ListTile(
                leading: const Icon(Icons.video_library),
                title: const Text('Choose video'),
                onTap: () {
                  Navigator.pop(context);
                  _pickAndUploadEvidence(isVideo: true, fromCamera: false);
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _pickAndUploadEvidence({
    required bool isVideo,
    required bool fromCamera,
  }) async {
    try {
      String? path;
      if (isVideo) {
        final XFile? file = await _picker.pickVideo(
          source: fromCamera ? ImageSource.camera : ImageSource.gallery,
          maxDuration: const Duration(minutes: 2),
        );
        path = file?.path;
      } else {
        final XFile? file = await _picker.pickImage(
          source: fromCamera ? ImageSource.camera : ImageSource.gallery,
          imageQuality: 85,
        );
        path = file?.path;
      }
      if (path == null || !mounted) return;

      setState(() => _uploadingEvidence = true);
      Position? position;
      try {
        position = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(accuracy: LocationAccuracy.medium),
        );
      } catch (_) {}

      await widget.apiService.uploadEvidence(
        widget.reportId,
        widget.deviceId,
        path,
        mediaLatitude: position?.latitude,
        mediaLongitude: position?.longitude,
        capturedAt: DateTime.now(),
        isLiveCapture: fromCamera,
      );

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Evidence added')),
      );
      await _loadReport();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to add evidence: ${e.toString().replaceFirst('Exception: ', '')}')),
        );
      }
    } finally {
      if (mounted) setState(() => _uploadingEvidence = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Report details'),
        actions: [
          if (_report != null && !_loading)
            IconButton(
              icon: _uploadingEvidence
                  ? const SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.add_photo_alternate),
              onPressed: _uploadingEvidence ? null : _showAddEvidenceOptions,
              tooltip: 'Add evidence',
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24.0),
                    child: Text(_error!, textAlign: TextAlign.center),
                  ),
                )
              : _report == null
                  ? const SizedBox.shrink()
                  : SingleChildScrollView(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _DetailRow(
                            label: 'Type',
                            value: _report!.incidentTypeName ?? '${_report!.incidentTypeId}',
                          ),
                          _DetailRow(
                            label: 'Status',
                            value: _report!.ruleStatus,
                          ),
                          _DetailRow(
                            label: 'Submitted',
                            value: _ReportCard._formatDate(_report!.reportedAt),
                          ),
                          _DetailRow(
                            label: 'Location',
                            value: '${_report!.latitude.toStringAsFixed(5)}, ${_report!.longitude.toStringAsFixed(5)}',
                          ),
                          if (_report!.description != null &&
                              _report!.description!.isNotEmpty) ...[
                            const SizedBox(height: 12),
                            Text(
                              'Description',
                              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                    color: Colors.grey[600],
                                  ),
                            ),
                            const SizedBox(height: 4),
                            Text(_report!.description!),
                          ],
                          const SizedBox(height: 20),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(
                                'Evidence',
                                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                      color: Colors.grey[600],
                                    ),
                              ),
                              TextButton.icon(
                                onPressed: _uploadingEvidence ? null : _showAddEvidenceOptions,
                                icon: const Icon(Icons.add, size: 20),
                                label: const Text('Add evidence'),
                              ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          if (_report!.evidenceFiles.isEmpty)
                            Padding(
                              padding: const EdgeInsets.only(bottom: 16),
                              child: Text(
                                'No evidence yet. You can add photos or videos within 72 hours of submitting.',
                                style: TextStyle(color: Colors.grey[600], fontSize: 14),
                              ),
                          )
                          else
                            _EvidenceGrid(evidence: _report!.evidenceFiles),
                        ],
                      ),
                    ),
    );
  }
}

class _EvidenceGrid extends StatelessWidget {
  final List<ReportEvidenceItem> evidence;

  const _EvidenceGrid({required this.evidence});

  @override
  Widget build(BuildContext context) {
    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 3,
        crossAxisSpacing: 8,
        mainAxisSpacing: 8,
        childAspectRatio: 1,
      ),
      itemCount: evidence.length,
      itemBuilder: (context, index) {
        final ef = evidence[index];
        final url = ApiConfig.evidenceFileUrl(ef.fileUrl);
        final isPhoto = ef.fileType.toLowerCase() == 'photo';
        return GestureDetector(
          onTap: () {
            // Could open fullscreen viewer
            if (isPhoto) {
              Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (context) => Scaffold(
                    appBar: AppBar(title: const Text('Evidence')),
                    body: InteractiveViewer(
                      child: Center(
                        child: Image.network(url, fit: BoxFit.contain),
                      ),
                    ),
                  ),
                ),
              );
            }
          },
          child: ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: isPhoto
                ? Image.network(
                    url,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => const ColoredBox(
                      color: Colors.grey,
                      child: Icon(Icons.broken_image, size: 32),
                    ),
                  )
                : ColoredBox(
                    color: Colors.grey.shade800,
                    child: Icon(Icons.videocam, color: Colors.grey.shade400, size: 32),
                  ),
          ),
        );
      },
    );
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;

  const _DetailRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  color: Colors.grey[600],
                ),
          ),
          const SizedBox(height: 2),
          Text(value, style: const TextStyle(fontSize: 16)),
        ],
      ),
    );
  }
}
