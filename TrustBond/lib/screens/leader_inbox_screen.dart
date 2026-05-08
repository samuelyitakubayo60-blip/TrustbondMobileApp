import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../services/leader_service.dart';

class LeaderInboxScreen extends StatefulWidget {
  const LeaderInboxScreen({super.key});

  @override
  State<LeaderInboxScreen> createState() => _LeaderInboxScreenState();
}

class _LeaderInboxScreenState extends State<LeaderInboxScreen> {
  final _leader = LeaderService();
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _items = [];
  Map<String, dynamic>? _me;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final me = await _leader.me();
      final rows = await _leader.listReports(onlyPending: true);
      final items = rows
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList(growable: false);
      if (!mounted) return;
      setState(() {
        _me = me;
        _items = items;
      });
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
        SnackBar(content: Text(e.toString())),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Leader Inbox'),
        backgroundColor: AppColors.bg,
        actions: [
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
          child: _loading
              ? const Center(child: CircularProgressIndicator(color: AppColors.accent))
              : _error != null
                  ? ListView(
                      padding: const EdgeInsets.all(24),
                      children: [
                        Text(_error!, style: const TextStyle(color: AppColors.danger)),
                        const SizedBox(height: 12),
                        ElevatedButton(
                          onPressed: _load,
                          child: const Text('Retry'),
                        ),
                      ],
                    )
                  : ListView(
                      padding: const EdgeInsets.all(16),
                      children: [
                        if (_me != null)
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: AppColors.card,
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(color: AppColors.border),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.verified_user, color: AppColors.accent),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        (_me!['full_name'] ?? 'Local Leader').toString(),
                                        style: const TextStyle(fontWeight: FontWeight.w700),
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
                          ),
                        const SizedBox(height: 12),
                        if (_items.isEmpty)
                          Container(
                            padding: const EdgeInsets.symmetric(vertical: 40),
                            alignment: Alignment.center,
                            child: const Text(
                              'No pending reports in your area.',
                              style: TextStyle(color: AppColors.muted),
                            ),
                          )
                        else
                          ..._items.map(_reportCard),
                        const SizedBox(height: 16),
                      ],
                    ),
        ),
      ),
    );
  }

  Widget _reportCard(Map<String, dynamic> r) {
    final id = (r['report_id'] ?? '').toString();
    final desc = (r['description'] ?? '').toString();
    final incident = (r['incident_type_name'] ?? 'Incident').toString();
    final village = (r['village_name'] ?? '').toString();
    final when = (r['reported_at'] ?? '').toString();

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(incident, style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(
            village.isNotEmpty ? '📍 $village' : '📍 Location in your coverage',
            style: const TextStyle(fontSize: 11, color: AppColors.muted),
          ),
          const SizedBox(height: 6),
          Text(
            desc.isNotEmpty ? desc : 'No description',
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 12, height: 1.3),
          ),
          const SizedBox(height: 8),
          Text('Reported: $when', style: const TextStyle(fontSize: 10, color: AppColors.muted)),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: ElevatedButton(
                  onPressed: () => _decision(id, 'confirmed'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.ok,
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  child: const Text('Confirm'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: ElevatedButton(
                  onPressed: () => _decision(id, 'rejected'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.danger,
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  child: const Text('Reject'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

