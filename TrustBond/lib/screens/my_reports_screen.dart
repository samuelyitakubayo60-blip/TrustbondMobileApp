import 'package:flutter/material.dart';
import 'dart:async';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../services/api_service.dart';
import '../services/device_service.dart';
import '../services/offline_report_queue.dart';
import '../services/local_cache_service.dart';
import '../services/app_refresh_bus.dart';
import '../models/report_model.dart';
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
  final _offlineQueue = OfflineReportQueue();
  final _cache = LocalCacheService();

  String? _deviceId;
  List<ReportListItem> _reports = [];
  bool _loading = true;
  int _filterIndex = 0;
  bool _showingCached = false;
  Timer? _syncTimer;
  Timer? _serverRefreshTimer;
  StreamSubscription<String>? _refreshSub;
  OfflineQueueStats _queueStats =
      const OfflineQueueStats(queuedCount: 0, errorCount: 0);
  List<OfflineQueueItem> _pendingQueueItems = const [];
  bool _retrying = false;

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
    _refreshQueueStats();
    _refreshPendingQueue();
    _syncTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      _offlineQueue.syncIfNeeded();
      _refreshQueueStats();
      _refreshPendingQueue();
    });
    _serverRefreshTimer = Timer.periodic(const Duration(seconds: 20), (_) {
      if (!mounted || _loading) return;
      _load();
    });
    _refreshSub = AppRefreshBus.stream.listen((_) {
      _load();
      _refreshQueueStats();
      _refreshPendingQueue();
    });
  }

  @override
  void dispose() {
    _syncTimer?.cancel();
    _serverRefreshTimer?.cancel();
    _refreshSub?.cancel();
    _tabCtrl.dispose();
    super.dispose();
  }

  Future<void> _refreshQueueStats() async {
    final stats = await _offlineQueue.getStats();
    if (!mounted) return;
    setState(() => _queueStats = stats);
  }

  Future<void> _refreshPendingQueue() async {
    final items = await _offlineQueue.getPendingItems();
    if (!mounted) return;
    setState(() => _pendingQueueItems = items);
  }

  Future<void> _retryAllFailed() async {
    if (_retrying) return;
    setState(() => _retrying = true);
    try {
      await _offlineQueue.retryAllFailedNow();
      await _refreshQueueStats();
      await _refreshPendingQueue();
      await _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Retry started for failed background items.')),
      );
    } finally {
      if (mounted) setState(() => _retrying = false);
    }
  }

  Future<void> _retryOne(String queueId) async {
    await _offlineQueue.retryNow(queueId);
    await _refreshQueueStats();
    await _refreshPendingQueue();
    await _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    
    // Use ensureDeviceId to get the proper backend device ID
    String? deviceId;
    try {
      deviceId = await _deviceService.ensureDeviceId();
    } catch (_) {
      deviceId = await _deviceService.getDeviceId();
    }
    debugPrint('MyReports: Device ID from ensureDeviceId: $deviceId');
    
    if (deviceId == null || deviceId.isEmpty) {
      setState(() {
        _loading = false;
        _deviceId = null;
        _error = 'Device not registered';
      });
      return;
    }
    _deviceId = deviceId;
    debugPrint('MyReports: Loading reports for device: $_deviceId');
    
    try {
      final list = await _apiService.getMyReports(deviceId);
      await _cache.cacheReports(deviceId, list);
      debugPrint('MyReports: Retrieved ${list.length} reports');
      
      // Parse each report individually to catch the exact error
      final parsedReports = <ReportListItem>[];
      for (int i = 0; i < list.length; i++) {
        try {
          final reportData = list[i] as Map<String, dynamic>;
          debugPrint('MyReports: Parsing report $i: ${reportData['report_id']}');
          final report = ReportListItem.fromJson(reportData);
          parsedReports.add(report);
        } catch (e) {
          debugPrint('MyReports: Failed to parse report $i: $e');
          debugPrint('MyReports: Report data: ${list[i]}');
          // Continue with other reports instead of failing completely
        }
      }
      
      setState(() {
        _reports = parsedReports;
        _showingCached = false;
        _loading = false;
      });
    } catch (e) {
      final cached = await _cache.getCachedReports(deviceId);
      if (cached.isNotEmpty) {
        final parsedReports = <ReportListItem>[];
        for (int i = 0; i < cached.length; i++) {
          try {
            parsedReports.add(ReportListItem.fromJson(cached[i]));
          } catch (_) {}
        }

        setState(() {
          _reports = parsedReports;
          _showingCached = true;
          _error = null;
          _loading = false;
        });
        return;
      }

      debugPrint('Failed to load my reports: $e');
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _loading = false;
      });
    }
  }

  List<ReportListItem> get _filtered {
    if (_filterIndex == 0) return _reports;
    final key = _filters[_filterIndex].toLowerCase();
    return _reports.where((r) {
      final s = r.ruleStatus.toLowerCase();
      if (key == 'pending') return s == 'pending' || s == 'processing';
      if (key == 'verified') {
        return s == 'confirmed' || s == 'verified' || s == 'trusted' || s == 'passed';
      }
      if (key == 'rejected') return s == 'rejected' || s == 'flagged';
      return true;
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildHeader(),
            if (_queueStats.totalCount > 0) _buildSyncIndicator(),
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
          const Text('My Reports',
              style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700)),
          const Spacer(),
          Text(
            _showingCached
                ? '${_reports.length} cached'
                : '${_reports.length} total',
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

  Widget _buildSyncIndicator() {
    final pending = _queueStats.queuedCount;
    final errors = _queueStats.errorCount;

    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: AppColors.surface2,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: errors > 0
                ? AppColors.warn.withValues(alpha: 0.5)
                : AppColors.accent.withValues(alpha: 0.4),
          ),
        ),
        child: Row(
          children: [
            SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: errors > 0 ? AppColors.warn : AppColors.accent,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                pending > 0
                    ? 'Background sync in progress: $pending item${pending == 1 ? '' : 's'} pending'
                    : 'Background sync has issues: $errors item${errors == 1 ? '' : 's'} need retry',
                style: const TextStyle(fontSize: 11.5, color: AppColors.text),
              ),
            ),
            if (errors > 0)
              TextButton(
                onPressed: _retrying ? null : _retryAllFailed,
                child: Text(_retrying ? 'Retrying...' : 'Retry'),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(
          child: CircularProgressIndicator(color: AppColors.accent));
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off, color: AppColors.muted, size: 48),
              const SizedBox(height: 12),
              const Text('Could not load reports',
                  style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              Text(_error!,
                  style: const TextStyle(fontSize: 12, color: AppColors.muted),
                  textAlign: TextAlign.center),
              const SizedBox(height: 16),
              ElevatedButton.icon(
                onPressed: _load,
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Retry'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10)),
                ),
              ),
            ],
          ),
        ),
      );
    }
    final items = _filtered;
    final showPendingQueue = _filterIndex == 1 && _pendingQueueItems.isNotEmpty;
    if (items.isEmpty) {
      if (showPendingQueue) {
        return ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
          children: _buildPendingQueueCards(),
        );
      }
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.assignment_outlined,
                size: 48, color: AppColors.muted.withValues(alpha: 0.5)),
            const SizedBox(height: 12),
            const Text('No reports found',
                style: TextStyle(color: AppColors.muted)),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: () async {
        await _load();
        await _refreshQueueStats();
        await _refreshPendingQueue();
      },
      color: AppColors.accent,
      child: ListView.builder(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
        itemCount: items.length + (showPendingQueue ? _pendingQueueItems.length + 1 : 0),
        itemBuilder: (context, index) {
          if (showPendingQueue) {
            if (index == 0) {
              return const Padding(
                padding: EdgeInsets.only(bottom: 8),
                child: Text(
                  'Background Pending',
                  style: TextStyle(fontSize: 12, color: AppColors.muted, fontWeight: FontWeight.w600),
                ),
              );
            }
            if (index <= _pendingQueueItems.length) {
              final item = _pendingQueueItems[index - 1];
              return _buildPendingQueueCard(item);
            }
            final reportIndex = index - (_pendingQueueItems.length + 1);
            final r = items[reportIndex];
            return ReportItemCard(
              icon: iconForIncidentType(r.incidentTypeName ?? ''),
              iconBg: colorForIncidentType(r.incidentTypeName ?? '')
                  .withValues(alpha: 0.1),
              typeName: r.incidentTypeName ?? 'Incident',
              description: r.description ?? 'No description',
              timeLabel: timeAgo(r.reportedAt),
              statusLabel: formatStatus(r.ruleStatus),
              statusType: badgeTypeFromStatus(r.ruleStatus),
              reportNumber: r.reportNumber,
              trustScore: r.trustScore,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => ReportDetailScreen(
                    reportId: r.reportId,
                    deviceId: _deviceId ?? '',
                  ),
                ),
              ),
            );
          }

          final r = items[index];
          return ReportItemCard(
            icon: iconForIncidentType(r.incidentTypeName ?? ''),
            iconBg: colorForIncidentType(r.incidentTypeName ?? '')
                .withValues(alpha: 0.1),
            typeName: r.incidentTypeName ?? 'Incident',
            description: r.description ?? 'No description',
            timeLabel: timeAgo(r.reportedAt),
            statusLabel: formatStatus(r.ruleStatus),
            statusType: badgeTypeFromStatus(r.ruleStatus),
            reportNumber: r.reportNumber,
            trustScore: r.trustScore,
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => ReportDetailScreen(
                  reportId: r.reportId,
                  deviceId: _deviceId ?? '',
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  List<Widget> _buildPendingQueueCards() {
    return [
      const Padding(
        padding: EdgeInsets.only(bottom: 8),
        child: Text(
          'Background Pending',
          style: TextStyle(fontSize: 12, color: AppColors.muted, fontWeight: FontWeight.w600),
        ),
      ),
      ..._pendingQueueItems.map(_buildPendingQueueCard),
    ];
  }

  Widget _buildPendingQueueCard(OfflineQueueItem item) {
    final isError = item.status == 'error';
    final id = item.reportId?.isNotEmpty == true ? item.reportId! : item.queueId;
    final created = item.createdAt;
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: isError
              ? AppColors.warn.withValues(alpha: 0.45)
              : AppColors.accent.withValues(alpha: 0.35),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isError ? Icons.error_outline : Icons.cloud_upload,
                size: 16,
                color: isError ? AppColors.warn : AppColors.accent,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  isError ? 'Sync Failed (Will Retry)' : 'Pending Background Sync',
                  style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
                ),
              ),
              if (isError)
                TextButton(
                  onPressed: () => _retryOne(item.queueId),
                  child: const Text('Retry now'),
                ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Ref: #${id.substring(0, id.length.clamp(0, 10))} · Evidence: ${item.evidenceCount} · Attempts: ${item.attempts}',
            style: const TextStyle(fontSize: 11, color: AppColors.muted),
          ),
          if (created != null)
            Text(
              'Queued ${timeAgo(created.toLocal())}',
              style: const TextStyle(fontSize: 11, color: AppColors.muted),
            ),
          if (item.error != null && item.error!.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                item.error!,
                style: const TextStyle(fontSize: 11, color: AppColors.warn),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ),
        ],
      ),
    );
  }

}
