import 'dart:async';

import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../models/offline_report_queue_item.dart';
import '../models/report_model.dart';
import '../services/api_service.dart';
import '../services/app_refresh_bus.dart';
import '../services/device_service.dart';
import '../services/offline_report_queue_service.dart';
import '../widgets/shared_widgets.dart';
import 'report_detail_screen.dart';

class MyReportsScreen extends StatefulWidget {
  const MyReportsScreen({super.key});

  @override
  State<MyReportsScreen> createState() => _MyReportsScreenState();
}

class _MyReportsScreenState extends State<MyReportsScreen>
    with SingleTickerProviderStateMixin {
  final _apiService = ApiService();
  final _deviceService = DeviceService();
  final _queueService = OfflineReportQueueService();

  String? _deviceId;
  List<ReportListItem> _reports = [];
  List<OfflineReportQueueItem> _queuedReports = [];
  bool _loading = true;
  int _filterIndex = 0;
  Timer? _serverRefreshTimer;
  StreamSubscription<String>? _refreshSub;
  String? _error;

  static const _filters = ['All', 'Pending', 'Verified', 'Rejected'];

  late TabController _tabCtrl;

  @override
  void initState() {
    super.initState();
    _tabCtrl = TabController(length: _filters.length, vsync: this);
    _tabCtrl.addListener(() {
      if (!_tabCtrl.indexIsChanging) {
        setState(() => _filterIndex = _tabCtrl.index);
      }
    });
    _load();
    _serverRefreshTimer = Timer.periodic(const Duration(seconds: 20), (_) {
      if (!mounted || _loading) return;
      _load(showSpinner: false);
    });
    _refreshSub = AppRefreshBus.stream.listen((_) {
      _load(showSpinner: false);
    });
  }

  @override
  void dispose() {
    _serverRefreshTimer?.cancel();
    _refreshSub?.cancel();
    _tabCtrl.dispose();
    super.dispose();
  }

  Future<void> _load({bool showSpinner = true}) async {
    if (showSpinner) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }

    String? deviceId;
    try {
      deviceId = await _deviceService.ensureDeviceId();
    } catch (_) {
      deviceId = await _deviceService.getDeviceId();
    }
    _deviceId = deviceId;

    try {
      final localQueue = await _queueService.getQueuedReports();
      final parsedReports = <ReportListItem>[];

      if (deviceId != null && deviceId.isNotEmpty) {
        final list = await _apiService.getMyReports(deviceId);
        for (final item in list) {
          try {
            parsedReports.add(
              ReportListItem.fromJson(item as Map<String, dynamic>),
            );
          } catch (e) {
            debugPrint('MyReports: Failed to parse report: $e');
          }
        }
      }

      final remoteIds = parsedReports
          .map((report) => _normalizeId(report.reportId))
          .where((id) => id.isNotEmpty)
          .toSet();
      final removed = await _queueService.removeItemsSyncedOnServer(remoteIds);
      final queueForUi = removed > 0
          ? await _queueService.getQueuedReports()
          : localQueue;

      setState(() {
        _reports = parsedReports;
        _queuedReports = queueForUi;
        _loading = false;
        _error = null;
      });
    } catch (e) {
      final localQueue = await _queueService.getQueuedReports();
      setState(() {
        _queuedReports = localQueue;
        _error = e.toString().replaceFirst('Exception: ', '');
        _loading = false;
      });
    }
  }

  List<_HistoryEntry> get _entries {
    final remoteIds = _reports
        .map((report) => _normalizeId(report.reportId))
        .where((id) => id.isNotEmpty)
        .toSet();

    final entries = <_HistoryEntry>[
      ..._reports.map(_HistoryEntry.remote),
      ..._queuedReports
          .where((item) => !remoteIds.contains(_normalizeId(item.localReportId)))
          .map(_HistoryEntry.local),
    ];

    List<_HistoryEntry> filtered = entries;
    final key = _filters[_filterIndex].toLowerCase();
    if (key == 'pending') {
      filtered = entries.where((entry) {
        if (entry.local != null) return true;
        final status = entry.remote!.workflowStatus;
        return status == 'pending' || status == 'processing' || status == 'under_review';
      }).toList();
    } else if (key == 'verified') {
      filtered = entries.where((entry) {
        if (entry.local != null) return false;
        final status = entry.remote!.workflowStatus;
        return status == 'confirmed' ||
            status == 'verified' ||
            status == 'trusted' ||
            status == 'passed';
      }).toList();
    } else if (key == 'rejected') {
      filtered = entries.where((entry) {
        if (entry.local != null) return false;
        final status = entry.remote!.workflowStatus;
        return status == 'rejected' || status == 'flagged';
      }).toList();
    }

    filtered.sort((a, b) => b.reportedAt.compareTo(a.reportedAt));
    return filtered;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildHeader(),
            _buildTabs(),
            Expanded(child: _buildBody()),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
      child: Row(
        children: [
          const Text(
            'My Reports',
            style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
          ),
          const Spacer(),
          Text(
            '${_entries.length} total',
            style: const TextStyle(fontSize: 11, color: AppColors.muted),
          ),
        ],
      ),
    );
  }

  Widget _buildTabs() {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 20),
      height: 36,
      decoration: BoxDecoration(
        color: AppColors.surface2,
        borderRadius: BorderRadius.circular(10),
      ),
      child: TabBar(
        controller: _tabCtrl,
        indicator: BoxDecoration(
          color: AppColors.accent.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppColors.accent.withValues(alpha: 0.35)),
        ),
        indicatorSize: TabBarIndicatorSize.tab,
        labelColor: AppColors.accent,
        unselectedLabelColor: AppColors.muted,
        labelStyle: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
        unselectedLabelStyle: const TextStyle(fontSize: 12),
        dividerHeight: 0,
        tabs: _filters.map((f) => Tab(text: f)).toList(),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.accent),
      );
    }

    if (_error != null && _entries.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off, color: AppColors.muted, size: 48),
              const SizedBox(height: 12),
              const Text(
                'Could not load reports',
                style: TextStyle(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 6),
              Text(
                _error!,
                style: const TextStyle(fontSize: 12, color: AppColors.muted),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              ElevatedButton.icon(
                onPressed: () => _load(),
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Retry'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    }

    final items = _entries;
    if (items.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.assignment_outlined,
              size: 48,
              color: AppColors.muted.withValues(alpha: 0.5),
            ),
            const SizedBox(height: 12),
            const Text('No reports found', style: TextStyle(color: AppColors.muted)),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => _load(),
      color: AppColors.accent,
      child: ListView.builder(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
        itemCount: items.length,
        itemBuilder: (context, index) {
          final entry = items[index];
          return entry.local != null
              ? _buildQueuedReportCard(entry.local!)
              : _buildRemoteReportCard(entry.remote!);
        },
      ),
    );
  }

  Widget _buildRemoteReportCard(ReportListItem report) {
    final statusKey = report.workflowStatus;
    return Stack(
      children: [
        ReportItemCard(
          icon: iconForIncidentType(report.incidentTypeName ?? ''),
          iconBg: colorForIncidentType(report.incidentTypeName ?? '')
              .withValues(alpha: 0.1),
          typeName: report.incidentTypeName ?? 'Incident',
          description: report.description ?? 'No description',
          timeLabel: timeAgo(report.reportedAt),
          statusLabel: formatStatus(statusKey),
          statusType: badgeTypeFromStatus(statusKey),
          reportNumber: report.reportNumber,
          trustScore: statusKey == 'verified' ? report.trustScore : null,
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => ReportDetailScreen(
                reportId: report.reportId,
                deviceId: _deviceId ?? '',
              ),
            ),
          ),
        ),
        const Positioned(
          right: 10,
          bottom: 24,
          child: Icon(Icons.check, size: 12, color: AppColors.ok),
        ),
      ],
    );
  }

  Widget _buildQueuedReportCard(OfflineReportQueueItem report) {
    final icon = iconForIncidentType(report.incidentTypeName);
    final color = colorForIncidentType(report.incidentTypeName);
    final state = _deliveryState(report.state);

    return Stack(
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          margin: const EdgeInsets.only(bottom: 14),
          decoration: BoxDecoration(
            color: AppColors.card,
            border: Border.all(color: AppColors.border),
            borderRadius: BorderRadius.circular(18),
          ),
          child: Row(
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                alignment: Alignment.center,
                child: Text(icon, style: const TextStyle(fontSize: 18)),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      report.incidentTypeName,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      report.localReportId,
                      style: const TextStyle(
                        fontSize: 10,
                        color: AppColors.muted,
                        fontFamily: 'monospace',
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      report.description.isEmpty ? 'No description' : report.description,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 12, color: AppColors.muted),
                    ),
                    if (report.state == OfflineReportSyncState.failed) ...[
                      const SizedBox(height: 6),
                      GestureDetector(
                        onTap: () => _queueService.retry(report.localReportId),
                        child: const Text(
                          'Tap to retry',
                          style: TextStyle(
                            fontSize: 11,
                            color: AppColors.muted,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(height: 7),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          timeAgo(report.submittedAtDate),
                          style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.muted,
                            fontFamily: 'monospace',
                          ),
                        ),
                        const SizedBox.shrink(),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        Positioned(
          right: 10,
          bottom: 24,
          child: switch (state) {
            DeliveryUiState.pending => const Icon(
                Icons.access_time,
                size: 12,
                color: AppColors.muted,
              ),
            DeliveryUiState.syncing => const SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(
                  strokeWidth: 1.6,
                  color: AppColors.accent,
                ),
              ),
            DeliveryUiState.failed => const Icon(
                Icons.access_time,
                size: 12,
                color: AppColors.muted,
              ),
            DeliveryUiState.sent => const Icon(
                Icons.check,
                size: 12,
                color: AppColors.ok,
              ),
          },
        ),
      ],
    );
  }

  DeliveryUiState _deliveryState(OfflineReportSyncState state) {
    return switch (state) {
      OfflineReportSyncState.pending => DeliveryUiState.pending,
      OfflineReportSyncState.syncing => DeliveryUiState.syncing,
      OfflineReportSyncState.failed => DeliveryUiState.failed,
    };
  }
}

String _normalizeId(String value) => value.trim().toLowerCase();

class _HistoryEntry {
  final ReportListItem? remote;
  final OfflineReportQueueItem? local;

  const _HistoryEntry._({this.remote, this.local});

  factory _HistoryEntry.remote(ReportListItem report) =>
      _HistoryEntry._(remote: report);

  factory _HistoryEntry.local(OfflineReportQueueItem report) =>
      _HistoryEntry._(local: report);

  DateTime get reportedAt => local?.submittedAtDate ?? remote!.reportedAt;
}
