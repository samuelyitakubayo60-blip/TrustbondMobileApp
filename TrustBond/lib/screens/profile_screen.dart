import 'dart:async';

import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../models/report_model.dart';
import '../services/api_service.dart';
import '../services/app_refresh_bus.dart';
import '../services/device_service.dart';
import '../widgets/shared_widgets.dart';
import 'about_screen.dart';
import 'help_faq_screen.dart';
import 'privacy_security_screen.dart';
import 'settings_screen.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _api = ApiService();
  final _deviceService = DeviceService();
  StreamSubscription<String>? _refreshSub;

  int _totalReports = 0;
  int _verifiedReports = 0;
  double _trustScore = 0;
  ReportListItem? _latestReport;

  @override
  void initState() {
    super.initState();
    _loadData();
    _refreshSub = AppRefreshBus.stream.listen((_) {
      _loadData();
    });
  }

  @override
  void dispose() {
    _refreshSub?.cancel();
    super.dispose();
  }

  Future<void> _loadData() async {
    final deviceHash = await _deviceService.getDeviceHash();
    final deviceId = await _deviceService.getDeviceId();

    if (deviceHash.isEmpty) return;

    try {
      final profile = await _api.getDeviceProfile(deviceHash);
      final list = (deviceId == null || deviceId.isEmpty)
          ? <dynamic>[]
          : await _api.getMyReports(deviceId);
      final reports = list
          .map((e) => ReportListItem.fromJson(e as Map<String, dynamic>))
          .toList(growable: false)
        ..sort((a, b) => b.reportedAt.compareTo(a.reportedAt));

      if (!mounted) return;
      setState(() {
        _totalReports = (profile['total_reports'] as num?)?.toInt() ?? 0;
        _verifiedReports = (profile['trusted_reports'] as num?)?.toInt() ?? 0;
        _trustScore = (profile['device_trust_score'] as num?)?.toDouble() ?? 0;
        _latestReport = reports.isEmpty ? null : reports.first;
      });
    } catch (e) {
      debugPrint('Failed to load profile: $e');
    }
  }

  String _trustLevelLabel() {
    if (_totalReports == 0) {
      return 'New Reporter — submit your first report';
    }
    if (_trustScore <= 40) {
      return 'Building Trust ⭐';
    }
    if (_trustScore <= 70) {
      return 'Active Contributor ⭐⭐';
    }
    return 'Trusted Reporter ⭐⭐⭐';
  }

  String _latestStatus() {
    final r = _latestReport;
    if (r == null) return 'Received';

    final status = (r.status ?? r.ruleStatus).toLowerCase();
    if (r.verifiedAt != null || status.contains('verified') || status.contains('confirmed')) {
      return 'Verified';
    }
    if (status.contains('review') || status.contains('investigating') || status.contains('pending')) {
      return 'Under Review';
    }
    return 'Received';
  }

  String _latestDateLabel() {
    final r = _latestReport;
    if (r == null) return 'No reports submitted yet';
    final d = r.reportedAt;
    return 'Submitted on ${d.month}/${d.day}/${d.year}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            children: [
              _buildHeader(),
              const SizedBox(height: 20),
              _buildIdentityCard(),
              const SizedBox(height: 14),
              _buildStatsRow(),
              const SizedBox(height: 14),
              _buildTrustLevelCard(),
              const SizedBox(height: 14),
              _buildLatestReportStatus(),
              const SizedBox(height: 14),
              _buildMenuItems(),
              const SizedBox(height: 28),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Row(
        children: [
          const Text('Profile',
              style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700)),
          const Spacer(),
          GestureDetector(
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ),
            child: Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: AppColors.surface2,
                shape: BoxShape.circle,
                border: Border.all(color: AppColors.border),
              ),
              child: const Icon(Icons.settings, size: 18, color: AppColors.muted),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildIdentityCard() {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppColors.accent.withValues(alpha: 0.08),
            AppColors.accent2.withValues(alpha: 0.05),
          ],
        ),
        border: Border.all(color: AppColors.accent.withValues(alpha: 0.2)),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: LinearGradient(
                colors: [AppColors.accent, AppColors.accent2],
              ),
            ),
            child: const Center(
              child: Text('👤', style: TextStyle(fontSize: 26)),
            ),
          ),
          const SizedBox(width: 14),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Anonymous Reporter',
                    style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                SizedBox(height: 2),
                Text(
                  'Device identity protected',
                  style: TextStyle(fontSize: 11, color: AppColors.muted),
                ),
                SizedBox(height: 4),
                StatusBadge(label: 'Verified Device', type: BadgeType.ok),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatsRow() {
    return Row(
      children: [
        Expanded(
          child: StatBox(
            value: '$_totalReports',
            label: 'Reports Submitted',
            valueColor: AppColors.accent,
          ),
        ),
        const SizedBox(width: 9),
        Expanded(
          child: StatBox(
            value: '$_verifiedReports',
            label: 'Reports Verified',
            valueColor: AppColors.ok,
          ),
        ),
      ],
    );
  }

  Widget _buildTrustLevelCard() {
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
        children: [
          const Text('Trust Level',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(
            _trustLevelLabel(),
            style: const TextStyle(fontSize: 13, color: AppColors.text),
          ),
        ],
      ),
    );
  }

  Widget _buildLatestReportStatus() {
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
        children: [
          const Text('Report Status',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Row(
            children: [
              StatusBadge(label: _latestStatus(), type: BadgeType.info),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _latestDateLabel(),
                  style: const TextStyle(fontSize: 11, color: AppColors.muted),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildMenuItems() {
    return Column(
      children: [
        _menuItem(Icons.security, 'Privacy & Security', () {
          Navigator.push(context,
              MaterialPageRoute(builder: (_) => const PrivacySecurityScreen()));
        }),
        _menuItem(Icons.help_outline, 'Help & FAQ', () {
          Navigator.push(
              context, MaterialPageRoute(builder: (_) => const HelpFaqScreen()));
        }),
        _menuItem(Icons.info_outline, 'About TrustBond', () {
          Navigator.push(
              context, MaterialPageRoute(builder: (_) => const AboutScreen()));
        }),
      ],
    );
  }

  Widget _menuItem(IconData icon, String label, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
        decoration: BoxDecoration(
          color: AppColors.card,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            Icon(icon, size: 18, color: AppColors.muted),
            const SizedBox(width: 12),
            Expanded(
              child: Text(label,
                  style: const TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w500)),
            ),
            const Icon(Icons.chevron_right_rounded,
                size: 18, color: AppColors.muted),
          ],
        ),
      ),
    );
  }
}
