import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../services/leader_service.dart';
import '../services/notification_service.dart';
import '../services/api_service.dart';
import 'report_screen.dart';

class LeaderInboxScreen extends StatefulWidget {
  const LeaderInboxScreen({super.key});

  @override
  State<LeaderInboxScreen> createState() => _LeaderInboxScreenState();
}

class _LeaderInboxScreenState extends State<LeaderInboxScreen> {
  final _leader = LeaderService();
  final _api = ApiService();
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _items = [];
  Map<String, dynamic>? _me;
  bool _showPendingOnly = true;
  int _pendingCount = 0;
  int _confirmedCount = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _syncLeaderPushToken() async {
    if (defaultTargetPlatform == TargetPlatform.windows) return;
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
      
      // Get counts for dashboard
      final allRows = await _leader.listReports(onlyPending: false);
      final allItems = allRows
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList(growable: false);
      
      final pendingCount = allItems.where((item) => 
        (item['leader_verification_status'] ?? 'pending') == 'pending').length;
      final confirmedCount = allItems.where((item) => 
        (item['leader_verification_status'] ?? 'pending') == 'confirmed').length;
      
      if (!mounted) return;
      setState(() {
        _me = me;
        _items = items;
        _pendingCount = pendingCount;
        _confirmedCount = confirmedCount;
      });
      await _syncLeaderPushToken();
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
      backgroundColor: const Color(0xFFF5F7FA),
      appBar: AppBar(
        title: const Text(
          'Village Safety Dashboard',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        ),
        backgroundColor: const Color(0xFF1E3A8A),
        elevation: 0,
        actions: [
          IconButton(
            tooltip: 'Submit incident',
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => const ReportScreen(localLeaderSubmit: true),
                ),
              );
              if (mounted) _load();
            },
            icon: const Icon(Icons.add_circle_outline, color: Colors.white),
          ),
          IconButton(
            tooltip: 'Logout',
            onPressed: () async {
              await _leader.logout();
              if (!context.mounted) return;
              Navigator.of(context).pop();
            },
            icon: const Icon(Icons.logout, color: Colors.white),
          ),
        ],
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _load,
          color: const Color(0xFF1E3A8A),
          child: Column(
            children: [
              _buildStatsHeader(),
              _buildFilterToggle(),
              Expanded(
                child: _loading
                    ? const Center(child: CircularProgressIndicator(color: Color(0xFF1E3A8A)))
                    : _error != null
                        ? ListView(
                            padding: const EdgeInsets.all(24),
                            children: [
                              Text(_error!, style: const TextStyle(color: Colors.red)),
                              const SizedBox(height: 12),
                              ElevatedButton(
                                onPressed: _load,
                                child: const Text('Retry'),
                              ),
                            ],
                          )
                        : _items.isEmpty
                            ? _buildEmptyState()
                            : ListView(
                                padding: const EdgeInsets.all(16),
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
      padding: const EdgeInsets.all(20),
      decoration: const BoxDecoration(
        color: Color(0xFF1E3A8A),
        borderRadius: BorderRadius.only(
          bottomLeft: Radius.circular(20),
          bottomRight: Radius.circular(20),
        ),
      ),
      child: Column(
        children: [
          const Text(
            'Your Village Safety',
            style: TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.bold,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              _buildStatCard('Pending Review', _pendingCount.toString(), Colors.orange),
              _buildStatCard('Confirmed', _confirmedCount.toString(), Colors.green),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStatCard(String title, String count, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.2),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Column(
        children: [
          Text(
            count,
            style: TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.bold,
              color: color,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            title,
            style: const TextStyle(
              fontSize: 12,
              color: Colors.white,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFilterToggle() {
    return Container(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Expanded(
            child: GestureDetector(
              onTap: () {
                setState(() {
                  _showPendingOnly = true;
                });
                _load();
              },
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: _showPendingOnly ? const Color(0xFF1E3A8A) : Colors.grey[200],
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(8),
                    bottomLeft: Radius.circular(8),
                  ),
                ),
                child: Text(
                  'Need Verification',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: _showPendingOnly ? Colors.white : Colors.grey[600],
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
          ),
          Expanded(
            child: GestureDetector(
              onTap: () {
                setState(() {
                  _showPendingOnly = false;
                });
                _load();
              },
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: !_showPendingOnly ? const Color(0xFF1E3A8A) : Colors.grey[200],
                  borderRadius: const BorderRadius.only(
                    topRight: Radius.circular(8),
                    bottomRight: Radius.circular(8),
                  ),
                ),
                child: Text(
                  'All Incidents',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: !_showPendingOnly ? Colors.white : Colors.grey[600],
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLeaderInfo() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.grey[300]!),
      ),
      child: Row(
        children: [
          const Icon(Icons.verified_user, color: Color(0xFF1E3A8A)),
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
                  style: const TextStyle(fontSize: 11, color: Colors.grey),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            _showPendingOnly ? Icons.check_circle : Icons.security,
            size: 80,
            color: Colors.grey[400],
          ),
          const SizedBox(height: 16),
          Text(
            _showPendingOnly 
                ? 'No incidents need verification'
                : 'No incidents in your area',
            style: TextStyle(
              fontSize: 18,
              color: Colors.grey[600],
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            _showPendingOnly
                ? 'Great job keeping your village safe!'
                : 'Check back later for new reports',
            style: TextStyle(
              fontSize: 14,
              color: Colors.grey[500],
            ),
          ),
        ],
      ),
    );
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

    Color getPriorityColor() {
      switch (priority.toLowerCase()) {
        case 'urgent': return Colors.red;
        case 'high': return Colors.orange;
        case 'medium': return Colors.yellow[700]!;
        case 'low': return Colors.green;
        default: return Colors.grey;
      }
    }

    Color getStatusColor() {
      switch (status.toLowerCase()) {
        case 'confirmed': return Colors.green;
        case 'rejected': return Colors.red;
        case 'pending': return Colors.orange;
        default: return Colors.grey;
      }
    }

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      elevation: 2,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: getStatusColor().withOpacity(0.3),
          width: 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: getStatusColor().withOpacity(0.1),
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(12),
                topRight: Radius.circular(12),
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: getPriorityColor(),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Text(
                              priority.toUpperCase(),
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 10,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        incident,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF1E3A8A),
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: getStatusColor(),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    status.toUpperCase(),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.location_on, color: Colors.grey, size: 16),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        village.isNotEmpty ? village : 'Location in your coverage',
                        style: const TextStyle(
                          color: Colors.grey,
                          fontSize: 14,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Icon(Icons.schedule, color: Colors.grey, size: 16),
                    const SizedBox(width: 4),
                    Text(
                      when.isNotEmpty ? 'Reported: $when' : 'Time unknown',
                      style: const TextStyle(
                        color: Colors.grey,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
                if (desc.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(
                    desc,
                    style: const TextStyle(
                      fontSize: 14,
                      color: Color(0xFF374151),
                    ),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
          ),
          if (needsVerification)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.orange[50],
                border: Border(
                  top: BorderSide(color: Colors.orange[200]!),
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.warning, color: Colors.orange[700], size: 16),
                      const SizedBox(width: 4),
                      Text(
                        'Action Required',
                        style: TextStyle(
                          color: Colors.orange[700],
                          fontWeight: FontWeight.bold,
                          fontSize: 14,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Please verify if this incident actually occurred in your area:',
                    style: TextStyle(
                      fontSize: 12,
                      color: Color(0xFF6B7280),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: ElevatedButton(
                          onPressed: () => _decision(id, 'confirmed'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.green,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(8),
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
                      const SizedBox(width: 12),
                      Expanded(
                        child: ElevatedButton(
                          onPressed: () => _decision(id, 'rejected'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.red,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(8),
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
    );
  }
}

