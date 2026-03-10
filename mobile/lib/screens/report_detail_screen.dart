import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../config/api_config.dart';
import '../widgets/shared_widgets.dart';
import '../services/api_service.dart';
import '../models/report_model.dart';

class ReportDetailScreen extends StatefulWidget {
  final String reportId;
  final String deviceId;

  const ReportDetailScreen({
    super.key,
    required this.reportId,
    required this.deviceId,
  });

  @override
  State<ReportDetailScreen> createState() => _ReportDetailScreenState();
}

class _ReportDetailScreenState extends State<ReportDetailScreen> {
  final _apiService = ApiService();
  ReportDetailItem? _report;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final data =
          await _apiService.getReport(widget.reportId, widget.deviceId);
      setState(() {
        _report = ReportDetailItem.fromJson(data);
        _loading = false;
      });
    } catch (_) {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: _loading
            ? const Center(
                child: CircularProgressIndicator(color: AppColors.accent))
            : _report == null
                ? _buildError()
                : _buildContent(),
      ),
    );
  }

  Widget _buildError() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline, size: 40, color: AppColors.muted),
          const SizedBox(height: 12),
          const Text('Could not load report',
              style: TextStyle(color: AppColors.muted)),
          const SizedBox(height: 12),
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Go back'),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    final r = _report!;
    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(child: _buildAppBar(r)),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          sliver: SliverList(
            delegate: SliverChildListDelegate([
              _buildStatusCard(r),
              const SizedBox(height: 14),
              _buildInfoCard(r),
              const SizedBox(height: 14),
              _buildDescCard(r),
              const SizedBox(height: 14),
              _buildLocationCard(r),
              if (r.evidenceFiles.isNotEmpty) ...[
                const SizedBox(height: 14),
                _buildEvidenceSection(r),
              ],
              const SizedBox(height: 14),
              _buildTimeline(r),
              const SizedBox(height: 28),
            ]),
          ),
        ),
      ],
    );
  }

  Widget _buildAppBar(ReportDetailItem r) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 20, 12),
      child: Row(
        children: [
          IconButton(
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.arrow_back_ios_new, size: 18),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Report Detail',
                    style:
                        TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                Text(
                  '#${r.reportId.substring(0, r.reportId.length.clamp(0, 8))}',
                  style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.muted,
                      fontFamily: 'monospace'),
                ),
              ],
            ),
          ),
          StatusBadge(
            label: formatStatus(r.ruleStatus),
            type: badgeTypeFromStatus(r.ruleStatus),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusCard(ReportDetailItem r) {
    final color = _statusColor(r.ruleStatus);
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        border: Border.all(color: color.withValues(alpha: 0.25)),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: color.withValues(alpha: 0.15),
            ),
            child: Icon(_statusIcon(r.ruleStatus), color: color, size: 20),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  formatStatus(r.ruleStatus),
                  style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: color),
                ),
                Text(
                  _statusDescription(r.ruleStatus),
                  style:
                      const TextStyle(fontSize: 11, color: AppColors.muted),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInfoCard(ReportDetailItem r) {
    return _card([
      _infoRow('Type', r.incidentTypeName ?? 'Incident'),
      _infoRow('Submitted', _formatDate(r.reportedAt)),
      _infoRow('Report ID', r.reportId.substring(0, r.reportId.length.clamp(0, 12))),
    ]);
  }

  Widget _buildDescCard(ReportDetailItem r) {
    return _card([
      const Row(
        children: [
          Text('📝', style: TextStyle(fontSize: 14)),
          SizedBox(width: 6),
          Text('Description',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
        ],
      ),
      const SizedBox(height: 8),
      Text(
        r.description ?? 'No description provided',
        style: const TextStyle(fontSize: 13, color: AppColors.text, height: 1.5),
      ),
    ]);
  }

  Widget _buildLocationCard(ReportDetailItem r) {
    return _card([
      const Row(
        children: [
          Text('📍', style: TextStyle(fontSize: 14)),
          SizedBox(width: 6),
          Text('Location',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
        ],
      ),
      const SizedBox(height: 8),
      Container(
        height: 120,
        decoration: BoxDecoration(
          color: AppColors.surface2,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppColors.border),
        ),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.map_outlined,
                  size: 28, color: AppColors.accent2),
              const SizedBox(height: 6),
              Text(
                '${r.latitude.toStringAsFixed(6)}, ${r.longitude.toStringAsFixed(6)}',
                style: const TextStyle(
                    fontSize: 11,
                    fontFamily: 'monospace',
                    color: AppColors.accent),
              ),
            ],
          ),
        ),
      ),
    ]);
  }

  Widget _buildEvidenceSection(ReportDetailItem r) {
    return _card([
      Row(
        children: [
          const Text('📎', style: TextStyle(fontSize: 14)),
          const SizedBox(width: 6),
          const Text('Evidence',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
          const Spacer(),
          Text('${r.evidenceFiles.length} files',
              style: const TextStyle(fontSize: 11, color: AppColors.muted)),
        ],
      ),
      const SizedBox(height: 10),
      SizedBox(
        height: 80,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: r.evidenceFiles.length,
          separatorBuilder: (_, __) => const SizedBox(width: 8),
          itemBuilder: (context, i) {
            final ev = r.evidenceFiles[i];
            final url = ApiConfig.evidenceFileUrl(ev.fileUrl);
            final isPhoto = ev.fileType.toLowerCase() == 'photo';
            return GestureDetector(
              onTap: () {
                if (isPhoto) {
                  Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => Scaffold(
                      backgroundColor: AppColors.bg,
                      appBar: AppBar(title: const Text('Evidence')),
                      body: InteractiveViewer(
                        child: Center(child: Image.network(url, fit: BoxFit.contain)),
                      ),
                    ),
                  ));
                }
              },
              child: ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: isPhoto
                    ? Image.network(url,
                        width: 80,
                        height: 80,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => Container(
                              width: 80,
                              height: 80,
                              color: AppColors.surface3,
                              child: const Icon(Icons.broken_image,
                                  color: AppColors.muted),
                            ))
                    : Container(
                        width: 80,
                        height: 80,
                        color: AppColors.surface3,
                        child: const Icon(Icons.videocam,
                            color: AppColors.accent2, size: 28),
                      ),
              ),
            );
          },
        ),
      ),
    ]);
  }

  Widget _buildTimeline(ReportDetailItem r) {
    final validated = r.ruleStatus != 'pending';
    final verified = r.ruleStatus == 'confirmed' ||
        r.ruleStatus == 'verified' ||
        r.ruleStatus == 'trusted';

    final steps = [
      _Step('Submitted', _formatDate(r.reportedAt), true, true),
      _Step('Rule Validation', validated ? 'Complete' : 'Processing...', validated, !validated),
      _Step('AI Verification', verified ? 'Verified' : 'Pending', verified, !verified && validated),
      _Step('Police Review', 'Waiting', false, false),
    ];

    return _card([
      const Text('Processing Timeline',
          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
      const SizedBox(height: 14),
      ...List.generate(steps.length, (i) {
        final s = steps[i];
        final isLast = i == steps.length - 1;
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Column(
              children: [
                Container(
                  width: 20,
                  height: 20,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: s.done ? AppColors.accent : AppColors.surface3,
                    border: Border.all(
                        color: s.active || s.done
                            ? AppColors.accent
                            : AppColors.border,
                        width: 2),
                  ),
                  child: s.done
                      ? const Icon(Icons.check, size: 12, color: AppColors.bg)
                      : null,
                ),
                if (!isLast)
                  Container(
                    width: 2,
                    height: 28,
                    color: s.done
                        ? AppColors.accent.withValues(alpha: 0.4)
                        : AppColors.border,
                  ),
              ],
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(bottom: 14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(s.label,
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: s.done || s.active
                              ? AppColors.text
                              : AppColors.muted,
                        )),
                    Text(s.sub,
                        style: TextStyle(
                          fontSize: 11,
                          color:
                              s.active ? AppColors.accent : AppColors.muted,
                        )),
                  ],
                ),
              ),
            ),
          ],
        );
      }),
    ]);
  }

  Widget _card(List<Widget> children) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: children,
      ),
    );
  }

  Widget _infoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Text(label,
              style: const TextStyle(fontSize: 12, color: AppColors.muted)),
          const Spacer(),
          Text(value,
              style: const TextStyle(
                  fontSize: 12, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }



  Color _statusColor(String status) {
    final s = status.toLowerCase();
    if (s == 'confirmed' || s == 'verified' || s == 'trusted' || s == 'passed') {
      return AppColors.ok;
    }
    if (s == 'flagged') return AppColors.warn;
    if (s == 'rejected') return AppColors.danger;
    return AppColors.accent2;
  }

  IconData _statusIcon(String status) {
    final s = status.toLowerCase();
    if (s == 'confirmed' || s == 'verified' || s == 'trusted' || s == 'passed') {
      return Icons.check_circle;
    }
    if (s == 'flagged') return Icons.warning_rounded;
    if (s == 'rejected') return Icons.cancel;
    return Icons.hourglass_bottom;
  }

  String _statusDescription(String status) {
    final s = status.toLowerCase();
    if (s == 'confirmed' || s == 'verified') {
      return 'This report has been verified and accepted.';
    }
    if (s == 'flagged') {
      return 'This report has been flagged for review.';
    }
    if (s == 'rejected') return 'This report did not pass validation.';
    return 'This report is being processed by our system.';
  }

  String _formatDate(DateTime dt) {
    return '${dt.day}/${dt.month}/${dt.year} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }
}

class _Step {
  final String label;
  final String sub;
  final bool done;
  final bool active;

  _Step(this.label, this.sub, this.done, this.active);
}
