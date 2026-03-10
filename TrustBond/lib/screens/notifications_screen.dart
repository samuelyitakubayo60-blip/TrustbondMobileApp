import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../services/api_service.dart';
import '../services/device_service.dart';
import '../models/report_model.dart';

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  bool _loading = true;
  final List<_NotifItem> _items = [];

  @override
  void initState() {
    super.initState();
    _loadNotifications();
  }

  Future<void> _loadNotifications() async {
    setState(() => _loading = true);
    try {
      final deviceId = await DeviceService().getDeviceId();
      if (deviceId == null || deviceId.isEmpty) {
        setState(() => _loading = false);
        return;
      }

      // Build notifications from report status changes
      final list = await ApiService().getMyReports(deviceId);
      final reports = list
          .map((e) => ReportListItem.fromJson(e as Map<String, dynamic>))
          .toList();

      final notifs = <_NotifItem>[];
      for (final r in reports) {
        final status = r.ruleStatus;
        if (status == 'confirmed' || status == 'verified' || status == 'trusted') {
          notifs.add(_NotifItem(
            icon: '✅',
            title: 'Report Verified',
            body: '${r.incidentTypeName ?? "Report"} has been verified.',
            time: timeAgo(r.reportedAt),
            read: true,
            color: AppColors.accent,
          ));
        } else if (status == 'rejected' || status == 'suspicious') {
          notifs.add(_NotifItem(
            icon: '⚠️',
            title: 'Report Flagged',
            body: '${r.incidentTypeName ?? "Report"} was flagged as $status.',
            time: timeAgo(r.reportedAt),
            read: false,
            color: AppColors.warn,
          ));
        } else if (status == 'pending') {
          notifs.add(_NotifItem(
            icon: '🔄',
            title: 'Report Processing',
            body: '${r.incidentTypeName ?? "Report"} is being processed.',
            time: timeAgo(r.reportedAt),
            read: true,
            color: AppColors.accent2,
          ));
        }
      }

      setState(() {
        _items.clear();
        _items.addAll(notifs);
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
        child: Column(
          children: [
            _buildAppBar(context),
            Expanded(child: _buildBody()),
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
    if (_items.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.notifications_none_rounded,
                size: 48, color: AppColors.muted.withValues(alpha: 0.5)),
            const SizedBox(height: 12),
            const Text('No notifications yet',
                style: TextStyle(color: AppColors.muted, fontSize: 14)),
            const SizedBox(height: 4),
            const Text('Submit reports to see status updates here',
                style: TextStyle(color: AppColors.muted, fontSize: 11)),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _loadNotifications,
      color: AppColors.accent,
      child: ListView.builder(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        itemCount: _items.length,
        itemBuilder: (context, i) => _buildNotifItem(_items[i]),
      ),
    );
  }

  Widget _buildAppBar(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 20, 4),
      child: Row(
        children: [
          IconButton(
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.arrow_back_ios_new, size: 18),
          ),
          const Expanded(
            child: Text('Notifications',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          ),
          Text('${_items.length}',
              style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.muted,
                  fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  Widget _buildNotifItem(_NotifItem n) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: n.read ? AppColors.card : AppColors.card,
        border: Border.all(
            color: n.read ? AppColors.border : n.color.withValues(alpha: 0.25)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: n.color.withValues(alpha: 0.1),
            ),
            alignment: Alignment.center,
            child: Text(n.icon, style: const TextStyle(fontSize: 16)),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(n.title,
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight:
                                n.read ? FontWeight.w500 : FontWeight.w700,
                          )),
                    ),
                    if (!n.read)
                      Container(
                        width: 7,
                        height: 7,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: n.color,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 3),
                Text(n.body,
                    style:
                        const TextStyle(fontSize: 11, color: AppColors.muted),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis),
                const SizedBox(height: 4),
                Text(n.time,
                    style: const TextStyle(
                        fontSize: 10, color: AppColors.muted)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _NotifItem {
  final String icon;
  final String title;
  final String body;
  final String time;
  final bool read;
  final Color color;

  _NotifItem({
    required this.icon,
    required this.title,
    required this.body,
    required this.time,
    required this.read,
    required this.color,
  });
}
