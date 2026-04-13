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
              _buildCommunityConfirmationCard(r),
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
              if (_hasEvidenceQualityOrML(r)) ...[
                const SizedBox(height: 14),
                _buildEvidenceQualityCard(r),
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
            label: formatStatus(r.workflowStatus),
            type: badgeTypeFromStatus(r.workflowStatus),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusCard(ReportDetailItem r) {
    final status = r.workflowStatus;
    final color = _statusColor(status);
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
            child: Icon(_statusIcon(status), color: color, size: 20),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  formatStatus(status),
                  style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: color),
                ),
                Text(
                  _statusDescription(status),
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
    final rows = <Widget>[
      _infoRow('Type', r.incidentTypeName ?? 'Incident'),
      _infoRow('Submitted', _formatDate(r.reportedAt)),
      _infoRow('Report', r.reportNumber ?? r.reportId.substring(0, r.reportId.length.clamp(0, 12))),
    ];
    if (r.workflowStatus == 'verified' && r.trustScore != null) {
      rows.add(_infoRow('Trust score', '${r.trustScore!.round()} / 100'));
    }
    if (r.contextTags.isNotEmpty) {
      rows.add(_infoRow('Tags', r.contextTags.join(', ')));
    }
    if (r.isFlagged == true && (r.flagReason ?? '').isNotEmpty) {
      rows.add(Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.flag, size: 14, color: AppColors.danger),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                r.flagReason!,
                style: const TextStyle(fontSize: 11, color: AppColors.danger),
              ),
            ),
          ],
        ),
      ));
    }
    return _card(rows);
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
          separatorBuilder: (context, index) => const SizedBox(width: 8),
          itemBuilder: (context, i) {
            final ev = r.evidenceFiles[i];
            final url = ApiConfig.evidenceFileUrl(ev.fileUrl);
            final isPhoto = ev.fileType.toLowerCase() == 'photo';
            final quality = ev.aiQualityLabel;
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
                child: Stack(
                  children: [
                    isPhoto
                        ? Image.network(
                            url,
                            width: 80,
                            height: 80,
                            fit: BoxFit.cover,
                            errorBuilder: (context, error, stackTrace) => Container(
                              width: 80,
                              height: 80,
                              color: AppColors.surface3,
                              child: const Icon(Icons.broken_image, color: AppColors.muted),
                            ),
                          )
                        : Container(
                            width: 80,
                            height: 80,
                            color: AppColors.surface3,
                            child: const Icon(Icons.videocam, color: AppColors.accent2, size: 28),
                          ),
                    if (quality != null && quality.isNotEmpty)
                      Positioned(
                        left: 0,
                        right: 0,
                        bottom: 0,
                        child: Container(
                          padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 6),
                          color: AppColors.bg.withValues(alpha: 0.65),
                          child: Text(
                            quality.toUpperCase(),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: 9,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.5,
                              color: (quality == 'good' || quality == 'fair')
                                  ? AppColors.accent
                                  : AppColors.muted,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    ]);
  }

  bool _hasEvidenceQualityOrML(ReportDetailItem r) {
    if (r.trustScore != null) return true;
    for (final ev in r.evidenceFiles) {
      if (ev.aiQualityLabel != null ||
          ev.blurScore != null ||
          ev.tamperScore != null) {
        return true;
      }
    }
    return false;
  }

  Widget _buildEvidenceQualityCard(ReportDetailItem r) {
    final rows = <Widget>[
      const Row(
        children: [
          Text('🔬', style: TextStyle(fontSize: 14)),
          SizedBox(width: 6),
          Text('Evidence quality & verification',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
        ],
      ),
      const SizedBox(height: 10),
    ];

    if (r.workflowStatus == 'verified' && r.trustScore != null) {
      final score = (r.trustScore ?? 0).round();
      rows.add(Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(
          children: [
            const Icon(Icons.verified_user_outlined, size: 16, color: AppColors.accent),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'Report trust score: $score/100 (from verification system)',
                style: const TextStyle(fontSize: 11, color: AppColors.text),
              ),
            ),
          ],
        ),
      ));
    }

    for (var i = 0; i < r.evidenceFiles.length; i++) {
      final ev = r.evidenceFiles[i];
      final hasQuality = ev.aiQualityLabel != null ||
          ev.blurScore != null ||
          ev.tamperScore != null;
      if (!hasQuality) continue;

      final parts = <String>[
        ev.fileType == 'video' ? 'Video ${i + 1}' : 'Photo ${i + 1}',
        if (ev.aiQualityLabel != null) 'Quality: ${ev.aiQualityLabel}',
        if (ev.blurScore != null) 'Blur: ${(ev.blurScore ?? 0).toStringAsFixed(2)}',
        if (ev.tamperScore != null) 'Tamper: ${(ev.tamperScore ?? 0).toStringAsFixed(2)}',
      ];
      rows.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.photo_library_outlined, size: 14, color: AppColors.muted),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                parts.join(' · '),
                style: const TextStyle(fontSize: 11, color: AppColors.muted),
              ),
            ),
          ],
        ),
      ));
    }

    return _card(rows);
  }

  Widget _buildTimeline(ReportDetailItem r) {
    final validated = r.ruleStatus != 'pending';
    // Backend uses rule_status values like "passed" for auto-verified reports.
    // Treat "passed" as verified in the mobile timeline.
    final verified = r.ruleStatus == 'passed' ||
        r.ruleStatus == 'confirmed' ||
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
    if (s == 'passed' || s == 'trusted') {
      return 'This report passed automated checks and is awaiting police review.';
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

  Widget _buildCommunityConfirmationCard(ReportDetailItem r) {
    if (r.deviceId == widget.deviceId) {
      // Cannot vote on own report
      return const SizedBox.shrink();
    }
    
    final total = r.communityVotes.values.fold(0, (sum, v) => sum + v);
    final real = r.communityVotes['real'] ?? 0;
    final falseVotes = r.communityVotes['false'] ?? 0;
    final unknown = r.communityVotes['unknown'] ?? 0;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 10,
            offset: const Offset(0, 4),
          )
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.how_to_vote_outlined, size: 18, color: AppColors.accent),
              SizedBox(width: 8),
              Text('Community Consensus',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 6),
          const Text('Help verify this report. Your vote impacts the credibility score and protects the community.', 
             style: TextStyle(fontSize: 12, color: AppColors.text, height: 1.4)),
          const SizedBox(height: 16),
          // Voting buttons
          Row(
            children: [
              Expanded(child: _voteButton('real', 'Real', Icons.check_circle_outline, AppColors.ok, r.userVote)),
              const SizedBox(width: 8),
              Expanded(child: _voteButton('false', 'False', Icons.cancel_outlined, AppColors.danger, r.userVote)),
              const SizedBox(width: 8),
              Expanded(child: _voteButton('unknown', 'Unknown', Icons.help_outline, AppColors.muted, r.userVote)),
            ],
          ),
          // Vote summary bar if there are votes
          if (total > 0) ...[
            const SizedBox(height: 20),
            ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: Row(
                children: [
                  if (real > 0)
                    Expanded(flex: real, child: Container(height: 6, color: AppColors.ok)),
                  if (unknown > 0)
                    Expanded(flex: unknown, child: Container(height: 6, color: AppColors.muted)),
                  if (falseVotes > 0)
                    Expanded(flex: falseVotes, child: Container(height: 6, color: AppColors.danger)),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('$real Real', style: const TextStyle(fontSize: 11, color: AppColors.ok, fontWeight: FontWeight.w700)),
                Text('$total total votes', style: const TextStyle(fontSize: 11, color: AppColors.muted)),
                Text('$falseVotes False', style: const TextStyle(fontSize: 11, color: AppColors.danger, fontWeight: FontWeight.w700)),
              ],
            ),
          ]
        ]
      ),
    );
  }

  Widget _voteButton(String voteValue, String label, IconData icon, Color baseColor, String? currentVote) {
    final isSelected = currentVote == voteValue;
    return InkWell(
      onTap: () => _submitVote(voteValue),
      borderRadius: BorderRadius.circular(12),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          color: isSelected ? baseColor.withValues(alpha: 0.15) : AppColors.surface2,
          border: Border.all(
            color: isSelected ? baseColor.withValues(alpha: 0.5) : Colors.transparent,
            width: 1.5,
          ),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          children: [
            Icon(icon, size: 22, color: isSelected ? baseColor : AppColors.muted),
            const SizedBox(height: 6),
            Text(label, 
              style: TextStyle(
                fontSize: 12, 
                fontWeight: isSelected ? FontWeight.w700 : FontWeight.w600,
                color: isSelected ? baseColor : AppColors.text,
              )
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _submitVote(String vote) async {
    if (_report == null) return;
    final r = _report!;
    
    // Optimistic UI update
    setState(() {
      final oldVote = r.userVote;
      if (oldVote == vote) return; // Unchanged
      
      final currentVotes = Map<String, int>.from(r.communityVotes);
      if (oldVote != null && currentVotes[oldVote] != null && currentVotes[oldVote]! > 0) {
        currentVotes[oldVote] = currentVotes[oldVote]! - 1;
      }
      currentVotes[vote] = (currentVotes[vote] ?? 0) + 1;
      
      _report = ReportDetailItem(
        reportId: r.reportId,
        deviceId: r.deviceId,
        incidentTypeId: r.incidentTypeId,
        incidentTypeName: r.incidentTypeName,
        description: r.description,
        latitude: r.latitude,
        longitude: r.longitude,
        reportedAt: r.reportedAt,
        ruleStatus: r.ruleStatus,
        evidenceFiles: r.evidenceFiles,
        trustScore: r.trustScore,
        reportNumber: r.reportNumber,
        contextTags: r.contextTags,
        isFlagged: r.isFlagged,
        flagReason: r.flagReason,
        communityVotes: currentVotes,
        userVote: vote,
      );
    });

    try {
      await _apiService.submitCommunityVote(r.reportId, widget.deviceId, vote);
      // Reload from server to get fresh trust scores after vote
      _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Failed to vote: $e'),
          backgroundColor: AppColors.danger,
        ));
        _load(); // Revert to server state
      }
    }
  }
}

class _Step {
  final String label;
  final String sub;
  final bool done;
  final bool active;

  _Step(this.label, this.sub, this.done, this.active);
}
