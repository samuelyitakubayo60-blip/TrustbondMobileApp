import 'dart:async';

import 'package:flutter/material.dart';

import '../config/api_config.dart';
import '../config/theme.dart';
import '../services/leader_service.dart';

class LeaderReportDetailScreen extends StatefulWidget {
  final String reportId;

  /// Pre-loaded summary data from the inbox list (shown while detail loads).
  final Map<String, dynamic>? previewData;

  const LeaderReportDetailScreen({
    super.key,
    required this.reportId,
    this.previewData,
  });

  @override
  State<LeaderReportDetailScreen> createState() =>
      _LeaderReportDetailScreenState();
}

class _LeaderReportDetailScreenState extends State<LeaderReportDetailScreen> {
  final _leader = LeaderService();
  final _noteController = TextEditingController();

  Map<String, dynamic>? _report;
  bool _loading = true;
  String? _error;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    if (widget.previewData != null) {
      _report = Map<String, dynamic>.from(widget.previewData!);
    }
    _loadDetail();
  }

  @override
  void dispose() {
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _loadDetail() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await _leader.getReport(widget.reportId);
      if (!mounted) return;
      setState(() => _report = data);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _submitDecision(String decision) async {
    final note = _noteController.text.trim();
    setState(() => _submitting = true);
    try {
      await _leader.verifyReport(
        reportId: widget.reportId,
        decision: decision,
        note: note.isNotEmpty ? note : null,
      );
      if (!mounted) return;
      // Refresh detail to show new status
      await _loadDetail();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            decision == 'confirmed'
                ? 'Report confirmed successfully.'
                : 'Report rejected.',
          ),
          backgroundColor:
              decision == 'confirmed' ? AppColors.accent : AppColors.danger,
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.toString()),
          backgroundColor: AppColors.surface2,
        ),
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  void _showDecisionDialog(String decision) {
    final isConfirm = decision == 'confirmed';
    showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.card,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text(
          isConfirm ? 'Confirm this report?' : 'Reject this report?',
          style: const TextStyle(
              fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              isConfirm
                  ? 'This will mark the incident as verified and raise the reporter\'s trust score.'
                  : 'This will mark the report as invalid and lower the reporter\'s trust score.',
              style:
                  const TextStyle(fontSize: 13, color: AppColors.muted, height: 1.4),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _noteController,
              maxLines: 3,
              maxLength: 300,
              style: const TextStyle(fontSize: 13, color: AppColors.text),
              decoration: InputDecoration(
                hintText: 'Add a note (optional)',
                hintStyle: const TextStyle(color: AppColors.muted),
                filled: true,
                fillColor: AppColors.surface2,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: AppColors.border),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: AppColors.border),
                ),
                contentPadding: const EdgeInsets.all(12),
                counterStyle:
                    const TextStyle(fontSize: 10, color: AppColors.muted),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel',
                style: TextStyle(color: AppColors.muted)),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: ElevatedButton.styleFrom(
              backgroundColor:
                  isConfirm ? AppColors.accent : AppColors.danger,
              foregroundColor: AppColors.bg,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10)),
            ),
            child: Text(isConfirm ? 'Confirm' : 'Reject'),
          ),
        ],
      ),
    ).then((confirmed) {
      if (confirmed == true) _submitDecision(decision);
    });
  }

  @override
  Widget build(BuildContext context) {
    final r = _report;
    final incident =
        (r?['incident_type_name'] ?? 'Incident').toString();

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        title: Text(
          incident,
          style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: AppColors.text),
        ),
        backgroundColor: AppColors.bg,
        elevation: 0,
        iconTheme: const IconThemeData(color: AppColors.text),
        actions: [
          if (!_loading && r != null)
            IconButton(
              tooltip: 'Refresh',
              onPressed: _loadDetail,
              icon: const Icon(Icons.refresh, color: AppColors.muted),
            ),
        ],
      ),
      body: SafeArea(
        child: _loading && r == null
            ? const Center(
                child:
                    CircularProgressIndicator(color: AppColors.accent))
            : _error != null && r == null
                ? _buildError()
                : _buildContent(r!),
      ),
    );
  }

  Widget _buildError() {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.error_outline, color: AppColors.danger, size: 48),
          const SizedBox(height: 12),
          Text(_error!,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.danger, fontSize: 13)),
          const SizedBox(height: 16),
          ElevatedButton(onPressed: _loadDetail, child: const Text('Retry')),
        ],
      ),
    );
  }

  Widget _buildContent(Map<String, dynamic> r) {
    final status =
        (r['leader_verification_status'] ?? 'pending').toString();
    final isPending = status == 'pending';

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
      children: [
        const SizedBox(height: 8),
        _buildStatusBanner(r),
        const SizedBox(height: 16),
        _buildInfoCard(r),
        const SizedBox(height: 12),
        _buildDescriptionCard(r),
        if (_hasEvidence(r)) ...[
          const SizedBox(height: 12),
          _buildEvidenceSection(r),
        ],
        if ((r['credibility_summary'] ?? '').toString().isNotEmpty) ...[
          const SizedBox(height: 12),
          _buildAiSummaryCard(r),
        ],
        if ((r['trust_score']) != null) ...[
          const SizedBox(height: 12),
          _buildTrustScoreCard(r),
        ],
        const SizedBox(height: 16),
        if (isPending)
          _buildActionSection()
        else ...[
          _buildDecisionResult(r),
          const SizedBox(height: 12),
          _buildOverallOutcomeCard(r),
        ],
      ],
    );
  }

  bool _hasEvidence(Map<String, dynamic> r) {
    final files = r['evidence_files'];
    if (files is List && files.isNotEmpty) return true;
    final count = int.tryParse(r['evidence_count']?.toString() ?? '0') ?? 0;
    return count > 0;
  }

  Widget _buildStatusBanner(Map<String, dynamic> r) {
    final status =
        (r['leader_verification_status'] ?? 'pending').toString();
    final priority = (r['priority'] ?? 'medium').toString();
    final priorityColor = _priorityColor(priority);
    final statusColor = _statusColor(status);

    return Row(
      children: [
        Container(
          padding:
              const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            color: priorityColor.withValues(alpha: 0.18),
            borderRadius: BorderRadius.circular(8),
            border:
                Border.all(color: priorityColor.withValues(alpha: 0.5)),
          ),
          child: Text(
            priority.toUpperCase(),
            style: TextStyle(
                color: priorityColor,
                fontSize: 10,
                fontWeight: FontWeight.w700),
          ),
        ),
        const SizedBox(width: 8),
        Container(
          padding:
              const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            color: statusColor.withValues(alpha: 0.18),
            borderRadius: BorderRadius.circular(8),
            border:
                Border.all(color: statusColor.withValues(alpha: 0.5)),
          ),
          child: Text(
            status.toUpperCase(),
            style: TextStyle(
                color: statusColor,
                fontSize: 10,
                fontWeight: FontWeight.w700),
          ),
        ),
        if ((r['evidence_count'] ?? 0) > 0) ...[
          const Spacer(),
          Row(
            children: [
              const Icon(Icons.attach_file,
                  size: 14, color: AppColors.muted),
              const SizedBox(width: 4),
              Text(
                '${r['evidence_count']} file(s)',
                style: const TextStyle(
                    fontSize: 12, color: AppColors.muted),
              ),
            ],
          ),
        ],
      ],
    );
  }

  Widget _buildInfoCard(Map<String, dynamic> r) {
    final village = (r['village_name'] ?? '').toString();
    final cell = (r['cell_name'] ?? '').toString();
    final sector = (r['sector_name'] ?? '').toString();
    final when = (r['reported_at'] ?? '').toString();

    String locationText = village;
    if (cell.isNotEmpty) locationText += ', $cell';
    if (sector.isNotEmpty) locationText += ', $sector';

    final shortId = widget.reportId.length >= 8
        ? widget.reportId.substring(0, 8)
        : widget.reportId;

    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _infoRow(Icons.tag, 'Report ID', '#$shortId'),
          if (locationText.isNotEmpty)
            _infoRow(Icons.location_on, 'Location', locationText),
          if (when.isNotEmpty)
            _infoRow(Icons.schedule, 'Reported', _formatDate(when)),
          if ((r['flag_reason'] ?? '').toString().isNotEmpty)
            _infoRow(Icons.flag, 'Flag reason',
                _humanizeFlag(r['flag_reason'].toString())),
        ],
      ),
    );
  }

  Widget _buildDescriptionCard(Map<String, dynamic> r) {
    final desc = (r['description'] ?? '').toString();
    if (desc.isEmpty) return const SizedBox.shrink();
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Citizen\'s Description',
              style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppColors.muted)),
          const SizedBox(height: 8),
          Text(
            desc,
            style: const TextStyle(
                fontSize: 14, color: AppColors.text, height: 1.5),
          ),
        ],
      ),
    );
  }

  Widget _buildEvidenceSection(Map<String, dynamic> r) {
    final files = r['evidence_files'];
    if (files is! List || files.isEmpty) {
      // No URL data yet — show count placeholder
      final count =
          int.tryParse(r['evidence_count']?.toString() ?? '0') ?? 0;
      return _card(
        child: Row(
          children: [
            const Icon(Icons.photo_library,
                color: AppColors.muted, size: 18),
            const SizedBox(width: 8),
            Text(
              '$count evidence file(s) attached',
              style: const TextStyle(
                  fontSize: 13, color: AppColors.muted),
            ),
          ],
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.only(left: 2, bottom: 8),
          child: Text('Evidence',
              style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.text)),
        ),
        SizedBox(
          height: 140,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: files.length,
            separatorBuilder: (context, index) => const SizedBox(width: 10),
            itemBuilder: (context, i) {
              final f = files[i] as Map<String, dynamic>;
              return _evidenceTile(f);
            },
          ),
        ),
      ],
    );
  }

  Widget _evidenceTile(Map<String, dynamic> f) {
    final rawUrl = (f['file_url'] ?? '').toString();
    final url = rawUrl.isNotEmpty
        ? ApiConfig.evidenceFileUrl(rawUrl)
        : '';
    final fileType = (f['file_type'] ?? 'photo').toString();
    final isVideo = fileType == 'video';
    final isLive = f['is_live_capture'] == true;

    return Container(
      width: 120,
      decoration: BoxDecoration(
        color: AppColors.surface2,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        fit: StackFit.expand,
        children: [
          if (url.isNotEmpty && !isVideo)
            Image.network(
              url,
              fit: BoxFit.cover,
              loadingBuilder: (_, child, progress) => progress == null
                  ? child
                  : const Center(
                      child: CircularProgressIndicator(
                          color: AppColors.accent, strokeWidth: 2)),
              errorBuilder: (context, error, stack) => const Center(
                child: Icon(Icons.broken_image,
                    color: AppColors.muted, size: 32),
              ),
            )
          else
            Center(
              child: Icon(
                isVideo ? Icons.videocam : Icons.image,
                color: AppColors.muted,
                size: 36,
              ),
            ),
          Positioned(
            bottom: 0,
            left: 0,
            right: 0,
            child: Container(
              padding: const EdgeInsets.symmetric(
                  horizontal: 6, vertical: 4),
              color: Colors.black.withValues(alpha: 0.55),
              child: Row(
                children: [
                  Icon(
                    isVideo
                        ? Icons.videocam
                        : Icons.photo,
                    size: 11,
                    color: Colors.white,
                  ),
                  const SizedBox(width: 4),
                  Text(
                    isVideo ? 'Video' : 'Photo',
                    style: const TextStyle(
                        fontSize: 10, color: Colors.white),
                  ),
                  if (isLive) ...[
                    const Spacer(),
                    const Icon(Icons.circle,
                        size: 7, color: Colors.greenAccent),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAiSummaryCard(Map<String, dynamic> r) {
    final summary = (r['credibility_summary'] ?? '').toString();
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.smart_toy_outlined,
                  size: 15, color: AppColors.accent),
              const SizedBox(width: 6),
              const Text('AI Screening Summary',
                  style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: AppColors.muted)),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            summary,
            style: const TextStyle(
                fontSize: 12,
                color: AppColors.muted,
                height: 1.5),
          ),
        ],
      ),
    );
  }

  Widget _buildTrustScoreCard(Map<String, dynamic> r) {
    final raw = r['trust_score'];
    final score = raw is num
        ? raw.toDouble()
        : double.tryParse(raw?.toString() ?? '') ?? 0.0;
    final color = score >= 70
        ? AppColors.accent
        : score >= 45
            ? AppColors.warn
            : AppColors.danger;

    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text('Credibility Score',
                  style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: AppColors.muted)),
              Text(
                score.toStringAsFixed(0),
                style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: color),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: (score / 100).clamp(0.0, 1.0),
              minHeight: 6,
              backgroundColor: AppColors.surface2,
              valueColor: AlwaysStoppedAnimation<Color>(color),
            ),
          ),
          const SizedBox(height: 6),
          Text(
            score >= 70
                ? 'High confidence — likely genuine'
                : score >= 45
                    ? 'Moderate — needs your review'
                    : 'Low — high chance of being false',
            style: const TextStyle(fontSize: 11, color: AppColors.muted),
          ),
        ],
      ),
    );
  }

  Widget _buildActionSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AppColors.warn.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
                color: AppColors.warn.withValues(alpha: 0.4)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(
                children: [
                  Icon(Icons.warning_amber_rounded,
                      color: AppColors.warn, size: 18),
                  SizedBox(width: 6),
                  Text(
                    'Your review is required',
                    style: TextStyle(
                        color: AppColors.warn,
                        fontWeight: FontWeight.w700,
                        fontSize: 14),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              const Text(
                'As the local leader for this area, please confirm whether this incident actually occurred.',
                style: TextStyle(
                    fontSize: 12, color: AppColors.muted, height: 1.4),
              ),
              const SizedBox(height: 16),
              if (_submitting)
                const Center(
                  child: CircularProgressIndicator(
                      color: AppColors.accent),
                )
              else
                Row(
                  children: [
                    Expanded(
                      child: ElevatedButton.icon(
                        onPressed: () =>
                            _showDecisionDialog('confirmed'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.accent,
                          foregroundColor: AppColors.bg,
                          padding: const EdgeInsets.symmetric(
                              vertical: 13),
                          shape: RoundedRectangleBorder(
                              borderRadius:
                                  BorderRadius.circular(10)),
                        ),
                        icon: const Icon(Icons.check_circle,
                            size: 16),
                        label: const Text('CONFIRM',
                            style: TextStyle(
                                fontWeight: FontWeight.w700)),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () =>
                            _showDecisionDialog('rejected'),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: AppColors.danger,
                          side: const BorderSide(
                              color: AppColors.danger),
                          padding: const EdgeInsets.symmetric(
                              vertical: 13),
                          shape: RoundedRectangleBorder(
                              borderRadius:
                                  BorderRadius.circular(10)),
                        ),
                        icon: const Icon(Icons.cancel, size: 16),
                        label: const Text('REJECT',
                            style: TextStyle(
                                fontWeight: FontWeight.w700)),
                      ),
                    ),
                  ],
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildDecisionResult(Map<String, dynamic> r) {
    final status =
        (r['leader_verification_status'] ?? '').toString();
    final isConfirmed = status == 'confirmed';
    final color =
        isConfirmed ? AppColors.accent : AppColors.danger;
    final note = (r['leader_note'] ?? '').toString();
    final verifiedAt =
        (r['leader_verified_at'] ?? '').toString();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: color.withValues(alpha: 0.4)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    isConfirmed
                        ? Icons.check_circle
                        : Icons.cancel,
                    color: color,
                    size: 20,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    isConfirmed
                        ? 'You confirmed this report'
                        : 'You rejected this report',
                    style: TextStyle(
                        color: color,
                        fontWeight: FontWeight.w700,
                        fontSize: 14),
                  ),
                ],
              ),
              if (verifiedAt.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(
                  _formatDate(verifiedAt),
                  style: const TextStyle(
                      fontSize: 11, color: AppColors.muted),
                ),
              ],
              if (note.isNotEmpty) ...[
                const SizedBox(height: 10),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AppColors.surface2,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: AppColors.border),
                  ),
                  child: Text(
                    '"$note"',
                    style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.muted,
                        fontStyle: FontStyle.italic,
                        height: 1.4),
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 12),
        // Allow changing decision
        const Text(
          'Change your decision',
          style: TextStyle(
              fontSize: 12,
              color: AppColors.muted,
              fontWeight: FontWeight.w500),
        ),
        const SizedBox(height: 8),
        if (_submitting)
          const Center(
              child: CircularProgressIndicator(
                  color: AppColors.accent))
        else
          Row(
            children: [
              if (!isConfirmed)
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () =>
                        _showDecisionDialog('confirmed'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.accent,
                      foregroundColor: AppColors.bg,
                      padding: const EdgeInsets.symmetric(
                          vertical: 11),
                      shape: RoundedRectangleBorder(
                          borderRadius:
                              BorderRadius.circular(10)),
                    ),
                    icon: const Icon(Icons.check_circle,
                        size: 15),
                    label: const Text('Change to Confirmed',
                        style: TextStyle(
                            fontWeight: FontWeight.w600,
                            fontSize: 12)),
                  ),
                ),
              if (!isConfirmed) const SizedBox(width: 10),
              if (isConfirmed)
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () =>
                        _showDecisionDialog('rejected'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.danger,
                      side: const BorderSide(
                          color: AppColors.danger),
                      padding: const EdgeInsets.symmetric(
                          vertical: 11),
                      shape: RoundedRectangleBorder(
                          borderRadius:
                              BorderRadius.circular(10)),
                    ),
                    icon: const Icon(Icons.cancel, size: 15),
                    label: const Text('Change to Rejected',
                        style: TextStyle(
                            fontWeight: FontWeight.w600,
                            fontSize: 12)),
                  ),
                ),
            ],
          ),
      ],
    );
  }

  Widget _buildOverallOutcomeCard(Map<String, dynamic> r) {
    final leaderStatus = (r['leader_verification_status'] ?? '').toString();
    final verificationStatus = (r['verification_status'] ?? '').toString();
    final isConfirmed = leaderStatus == 'confirmed';
    final isRejected = leaderStatus == 'rejected';

    final raw = r['trust_score'];
    final score = raw is num
        ? raw.toDouble()
        : double.tryParse(raw?.toString() ?? '') ?? 0.0;

    final Color headerColor;
    final IconData headerIcon;
    final String headline;
    final String subtext;

    if (isConfirmed) {
      headerColor = AppColors.accent;
      headerIcon = Icons.verified_rounded;
      headline = 'Incident VERIFIED';
      subtext = verificationStatus == 'verified'
          ? 'Visible on community safety map. Eligible for auto-cases and hotspot clusters.'
          : 'Your confirmation is recorded. Final system status: ${verificationStatus.replaceAll('_', ' ')}.';
    } else if (isRejected) {
      headerColor = AppColors.danger;
      headerIcon = Icons.cancel_rounded;
      headline = 'Incident REJECTED';
      subtext = 'Removed from community safety map. Will not feed cases or hotspot clusters.';
    } else {
      return const SizedBox.shrink();
    }

    final scoreColor = score >= 70
        ? AppColors.accent
        : score >= 45
            ? AppColors.warn
            : AppColors.danger;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: headerColor.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: headerColor.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(headerIcon, color: headerColor, size: 22),
              const SizedBox(width: 8),
              Text(
                headline,
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w800,
                  color: headerColor,
                  letterSpacing: 0.3,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            subtext,
            style: const TextStyle(fontSize: 12, color: AppColors.muted, height: 1.45),
          ),
          if (score > 0) ...[
            const SizedBox(height: 14),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'Final credibility score',
                  style: TextStyle(fontSize: 11, color: AppColors.muted),
                ),
                Text(
                  '${score.toStringAsFixed(0)} / 100',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: scoreColor,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: (score / 100).clamp(0.0, 1.0),
                minHeight: 7,
                backgroundColor: AppColors.surface2,
                valueColor: AlwaysStoppedAnimation<Color>(scoreColor),
              ),
            ),
            const SizedBox(height: 4),
            Text(
              isConfirmed
                  ? score >= 90
                      ? 'Score raised to ≥90 — leader confirmation applied'
                      : 'Score reflects AI + leader decision'
                  : 'Score set to low — leader rejection applied',
              style: const TextStyle(fontSize: 10, color: AppColors.muted),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              _outcomePill(
                icon: isConfirmed ? Icons.map_outlined : Icons.hide_source,
                label: isConfirmed ? 'On safety map' : 'Off safety map',
                color: headerColor,
              ),
              const SizedBox(width: 8),
              _outcomePill(
                icon: isConfirmed ? Icons.folder_open_outlined : Icons.block,
                label: isConfirmed ? 'Cases eligible' : 'Cases blocked',
                color: isConfirmed ? AppColors.accent2 : AppColors.muted,
              ),
              const SizedBox(width: 8),
              _outcomePill(
                icon: isConfirmed ? Icons.groups_outlined : Icons.person_off_outlined,
                label: isConfirmed ? 'Community active' : 'Inactive',
                color: isConfirmed ? AppColors.ok : AppColors.muted,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _outcomePill({required IconData icon, required String label, required Color color}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 11, color: color),
          const SizedBox(width: 4),
          Text(label, style: TextStyle(fontSize: 10, color: color, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  // ── helpers ──────────────────────────────────────────────────────────

  Widget _card({required Widget child}) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.border),
        ),
        child: child,
      );

  Widget _infoRow(IconData icon, String label, String value) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 15, color: AppColors.muted),
            const SizedBox(width: 8),
            Text('$label: ',
                style: const TextStyle(
                    fontSize: 12, color: AppColors.muted)),
            Expanded(
              child: Text(
                value,
                style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.text,
                    fontWeight: FontWeight.w500),
              ),
            ),
          ],
        ),
      );

  Color _priorityColor(String priority) {
    switch (priority.toLowerCase()) {
      case 'urgent':
        return AppColors.danger;
      case 'high':
        return AppColors.warn;
      case 'medium':
        return AppColors.accent2;
      default:
        return AppColors.muted;
    }
  }

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'confirmed':
        return AppColors.accent;
      case 'rejected':
        return AppColors.danger;
      default:
        return AppColors.warn;
    }
  }

  String _formatDate(String raw) {
    try {
      final dt = DateTime.parse(raw).toLocal();
      return '${dt.day}/${dt.month}/${dt.year}  ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) {
      return raw;
    }
  }

  String _humanizeFlag(String reason) {
    const map = {
      'incident_description_mismatch':
          'Description does not match incident type',
      'description_evidence_mismatch':
          'Description, media and incident type do not align',
      'evidence_incident_mismatch':
          'Uploaded media does not support incident type',
      'gibberish_description': 'Description appears unclear',
      'out_of_musanze_boundary': 'Location is outside service area',
      'device_burst_reporting':
          'Too many reports from this device recently',
      'duplicate_description_recent': 'Same description submitted repeatedly',
      'threshold_low_score': 'Credibility score too low',
      'rejected_by_local_leader': 'Rejected by local leader',
      'evidence_does_not_match_incident':
          'Evidence does not match incident type',
    };
    return map[reason.toLowerCase().replaceAll('-', '_')] ??
        reason.replaceAll('_', ' ').trim();
  }
}
