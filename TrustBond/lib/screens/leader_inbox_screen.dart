import 'dart:async';

import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../services/leader_service.dart';
import '../services/notification_service.dart';
import '../services/platform_service.dart';
import 'leader_report_detail_screen.dart';
import 'report_step1_screen.dart';

class LeaderInboxScreen extends StatefulWidget {
  const LeaderInboxScreen({super.key, this.initialReportId});

  /// Open inbox focused on this report (e.g. from FCM tap).
  final String? initialReportId;

  @override
  State<LeaderInboxScreen> createState() => _LeaderInboxScreenState();
}

class _LeaderInboxScreenState extends State<LeaderInboxScreen> {
  final _leader = LeaderService();
  final _scrollController = ScrollController();
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _items = [];
  Map<String, dynamic>? _me;
  bool _showPendingOnly = true;
  int _pendingCount = 0;
  int _confirmedCount = 0;
  String? _highlightReportId;
  StreamSubscription<String>? _deepLinkSub;
  final Map<String, GlobalKey> _reportKeys = {};

  @override
  void initState() {
    super.initState();
    _highlightReportId =
        widget.initialReportId ?? NotificationService().consumePendingLeaderReportId();
    if (_highlightReportId != null) {
      _showPendingOnly = true;
    }
    _deepLinkSub = NotificationService().leaderDeepLinkStream.listen(_onLeaderDeepLink);
    _load();
  }

  @override
  void dispose() {
    _deepLinkSub?.cancel();
    _scrollController.dispose();
    super.dispose();
  }

  void _onLeaderDeepLink(String reportId) {
    if (!mounted) return;
    setState(() {
      _highlightReportId = reportId;
      _showPendingOnly = true;
    });
    _load();
  }

  void _scrollToHighlightedReport() {
    final id = _highlightReportId;
    if (id == null) return;
    final key = _reportKeys[id];
    final ctx = key?.currentContext;
    if (ctx != null) {
      Scrollable.ensureVisible(
        ctx,
        duration: const Duration(milliseconds: 400),
        curve: Curves.easeInOut,
        alignment: 0.2,
      );
    }
  }

  Future<void> _syncLeaderPushToken() async {
    if (!PlatformService.supportsFirebase) return;
    try {
      final ns = NotificationService();
      await ns.initialize();
      final t = ns.fcmToken;
      if (t != null && t.isNotEmpty) {
        await _leader.registerFcmToken(fcmToken: t);
      }
    } catch (_) {}
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final me = await _leader.me();
      final rows = await _leader.listReports(onlyPending: _showPendingOnly);
      final items = rows
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList(growable: false);

      final allRows = await _leader.listReports(onlyPending: false);
      final allItems = allRows
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList(growable: false);

      final pendingCount = allItems
          .where((item) => (item['leader_verification_status'] ?? 'pending') == 'pending')
          .length;
      final confirmedCount = allItems
          .where((item) => (item['leader_verification_status'] ?? 'pending') == 'confirmed')
          .length;

      if (!mounted) return;
      setState(() {
        _me = me;
        _items = items;
        _pendingCount = pendingCount;
        _confirmedCount = confirmedCount;
      });
      if (_highlightReportId != null &&
          !items.any((e) => (e['report_id'] ?? '').toString() == _highlightReportId) &&
          _showPendingOnly) {
        final allPending = allItems
            .where((e) => (e['leader_verification_status'] ?? 'pending') == 'pending')
            .toList();
        if (allPending.any((e) => (e['report_id'] ?? '').toString() == _highlightReportId)) {
          setState(() => _items = allPending);
        }
      }
      await _syncLeaderPushToken();
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToHighlightedReport());
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _decision(String reportId, String decision) async {
    try {
      await _leader.verifyReport(reportId: reportId, decision: decision);
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.toString()),
          backgroundColor: AppColors.surface2,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        title: const Text(
          'Village Safety Dashboard',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w600,
            color: AppColors.text,
          ),
        ),
        backgroundColor: AppColors.bg,
        elevation: 0,
        iconTheme: const IconThemeData(color: AppColors.text),
        actions: [
          IconButton(
            tooltip: 'Submit incident',
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => const ReportStep1Screen(localLeaderSubmit: true),
                ),
              );
              if (mounted) _load();
            },
            icon: const Icon(Icons.add_circle_outline, color: AppColors.accent),
          ),
          IconButton(
            tooltip: 'Logout',
            onPressed: () async {
              await _leader.logout();
              if (!context.mounted) return;
              Navigator.of(context).pop();
            },
            icon: const Icon(Icons.logout, color: AppColors.muted),
          ),
        ],
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _load,
          color: AppColors.accent,
          backgroundColor: AppColors.surface2,
          child: Column(
            children: [
              _buildStatsHeader(),
              _buildFilterToggle(),
              Expanded(
                child: _loading
                    ? const Center(
                        child: CircularProgressIndicator(color: AppColors.accent),
                      )
                    : _error != null
                        ? ListView(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding: const EdgeInsets.all(24),
                            children: [
                              Text(
                                _error!,
                                style: const TextStyle(color: AppColors.danger),
                              ),
                              const SizedBox(height: 12),
                              ElevatedButton(
                                onPressed: _load,
                                child: const Text('Retry'),
                              ),
                            ],
                          )
                        : _items.isEmpty
                            ? ListView(
                                physics: const AlwaysScrollableScrollPhysics(),
                                children: [_buildEmptyState()],
                              )
                            : ListView(
                                controller: _scrollController,
                                physics: const AlwaysScrollableScrollPhysics(),
                                padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                                children: [
                                  if (_me != null) _buildLeaderInfo(),
                                  const SizedBox(height: 12),
                                  ..._items.map(_reportCard),
                                  const SizedBox(height: 16),
                                ],
                              ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildStatsHeader() {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        children: [
          const Text(
            'Your Village Safety',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _buildStatCard(
                  'Pending Review',
                  _pendingCount.toString(),
                  AppColors.warn,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildStatCard(
                  'Confirmed',
                  _confirmedCount.toString(),
                  AppColors.accent,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStatCard(String title, String count, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.surface2,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Column(
        children: [
          Text(
            count,
            style: TextStyle(
              fontSize: 26,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 11,
              color: AppColors.muted,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFilterToggle() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.surface2,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppColors.border),
        ),
        child: Row(
          children: [
            Expanded(child: _filterTab('Need Verification', true)),
            Expanded(child: _filterTab('All Incidents', false)),
          ],
        ),
      ),
    );
  }

  Widget _filterTab(String label, bool pendingTab) {
    final selected = pendingTab ? _showPendingOnly : !_showPendingOnly;
    return GestureDetector(
      onTap: () {
        setState(() => _showPendingOnly = pendingTab);
        _load();
      },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(vertical: 11),
        decoration: BoxDecoration(
          color: selected ? AppColors.accent2.withValues(alpha: 0.18) : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
          border: selected
              ? Border.all(color: AppColors.accent2.withValues(alpha: 0.5))
              : null,
        ),
        child: Text(
          label,
          textAlign: TextAlign.center,
          style: TextStyle(
            color: selected ? AppColors.accent2 : AppColors.muted,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
            fontSize: 13,
          ),
        ),
      ),
    );
  }

  Widget _buildLeaderInfo() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          const Icon(Icons.verified_user, color: AppColors.accent, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  (_me!['full_name'] ?? 'Local Leader').toString(),
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    color: AppColors.text,
                    fontSize: 14,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  'Coverage: ${((_me!['covered_location_ids'] as List?)?.length ?? 0)} locations',
                  style: const TextStyle(fontSize: 11, color: AppColors.muted),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            _showPendingOnly ? Icons.check_circle_outline : Icons.security,
            size: 72,
            color: AppColors.muted.withValues(alpha: 0.6),
          ),
          const SizedBox(height: 16),
          Text(
            _showPendingOnly
                ? 'No incidents need verification'
                : 'No incidents in your area',
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 17,
              color: AppColors.text,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            _showPendingOnly
                ? 'Great job keeping your village safe!'
                : 'Check back later for new reports',
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 13, color: AppColors.muted),
          ),
        ],
      ),
    );
  }

  Color _priorityColor(String priority) {
    switch (priority.toLowerCase()) {
      case 'urgent':
        return AppColors.danger;
      case 'high':
        return AppColors.warn;
      case 'medium':
        return AppColors.accent2;
      case 'low':
        return AppColors.accent;
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
      case 'pending':
        return AppColors.warn;
      default:
        return AppColors.muted;
    }
  }

  Widget _reportCard(Map<String, dynamic> r) {
    final id = (r['report_id'] ?? '').toString();
    final desc = (r['description'] ?? '').toString();
    final incident = (r['incident_type_name'] ?? 'Incident').toString();
    final village = (r['village_name'] ?? '').toString();
    final when = (r['reported_at'] ?? '').toString();
    final priority = (r['priority'] ?? 'medium').toString();
    final status = (r['leader_verification_status'] ?? 'pending').toString();
    final needsVerification = status == 'pending';
    final priorityColor = _priorityColor(priority);
    final statusColor = _statusColor(status);
    final isHighlighted = _highlightReportId != null && id == _highlightReportId;
    _reportKeys.putIfAbsent(id, GlobalKey.new);

    return GestureDetector(
      onTap: () async {
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => LeaderReportDetailScreen(
              reportId: id,
              previewData: r,
            ),
          ),
        );
        if (mounted) _load();
      },
      child: Container(
      key: _reportKeys[id],
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isHighlighted
              ? AppColors.accent2
              : AppColors.border,
          width: isHighlighted ? 1.5 : 1,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(14),
            color: statusColor.withValues(alpha: 0.12),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: priorityColor.withValues(alpha: 0.2),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: priorityColor.withValues(alpha: 0.5)),
                        ),
                        child: Text(
                          priority.toUpperCase(),
                          style: TextStyle(
                            color: priorityColor,
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        incident,
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.text,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(
                    color: statusColor.withValues(alpha: 0.25),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: statusColor.withValues(alpha: 0.5)),
                  ),
                  child: Text(
                    status.toUpperCase(),
                    style: TextStyle(
                      color: statusColor,
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.location_on, color: AppColors.muted, size: 16),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        village.isNotEmpty ? village : 'Location in your coverage',
                        style: const TextStyle(color: AppColors.muted, fontSize: 13),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    const Icon(Icons.schedule, color: AppColors.muted, size: 16),
                    const SizedBox(width: 4),
                    Text(
                      when.isNotEmpty ? 'Reported: $when' : 'Time unknown',
                      style: const TextStyle(color: AppColors.muted, fontSize: 12),
                    ),
                  ],
                ),
                if (desc.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Text(
                    desc,
                    style: const TextStyle(fontSize: 13, color: AppColors.text, height: 1.35),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
                if ((r['credibility_summary'] ?? '').toString().isNotEmpty) ...[
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
                      (r['credibility_summary'] ?? '').toString(),
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.muted,
                        height: 1.35,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (needsVerification)
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: AppColors.surface2,
                border: const Border(top: BorderSide(color: AppColors.border)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.warning_amber_rounded, color: AppColors.warn, size: 18),
                      SizedBox(width: 6),
                      Text(
                        'Action required',
                        style: TextStyle(
                          color: AppColors.warn,
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Please verify if this incident actually occurred in your area:',
                    style: TextStyle(fontSize: 12, color: AppColors.muted),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: ElevatedButton(
                          onPressed: () => _decision(id, 'confirmed'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppColors.accent,
                            foregroundColor: AppColors.bg,
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ),
                          child: const Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.check_circle, size: 16),
                              SizedBox(width: 4),
                              Text('CONFIRM'),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: OutlinedButton(
                          onPressed: () => _decision(id, 'rejected'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: AppColors.danger,
                            side: const BorderSide(color: AppColors.danger),
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ),
                          child: const Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.cancel, size: 16),
                              SizedBox(width: 4),
                              Text('REJECT'),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
        ],
      ),
    ),   // Container
    );   // GestureDetector
  }
}
