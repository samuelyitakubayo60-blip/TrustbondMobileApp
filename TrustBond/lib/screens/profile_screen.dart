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
import '../services/leader_service.dart';
import 'leader_inbox_screen.dart';
import 'leader_login_screen.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _api = ApiService();
  final _deviceService = DeviceService();
  final _leader = LeaderService();
  StreamSubscription<String>? _refreshSub;

  int _totalReports = 0;
  int _verifiedReports = 0;
  ReportListItem? _latestReport;
  bool _leaderSessionActive = false;
  String? _leaderName;
  String? _leaderEmail;

  @override
  void initState() {
    super.initState();
    _loadData();
    _refreshSub = AppRefreshBus.stream.listen((reason) {
      if (reason == 'leader_session') {
        _loadLeaderSession();
      } else {
        _loadData();
      }
    });
  }

  @override
  void dispose() {
    _refreshSub?.cancel();
    super.dispose();
  }

  Future<void> _loadLeaderSession() async {
    try {
      final active = await _leader.isSessionActive();
      if (!mounted) return;
      if (!active) {
        setState(() {
          _leaderSessionActive = false;
          _leaderName = null;
          _leaderEmail = null;
        });
        return;
      }
      final me = await _leader.me();
      if (!mounted) return;
      setState(() {
        _leaderSessionActive = true;
        _leaderName = me['full_name']?.toString();
        _leaderEmail = me['email']?.toString();
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _leaderSessionActive = false;
        _leaderName = null;
        _leaderEmail = null;
      });
    }
  }

  Future<void> _loadData() async {
    final deviceHash = await _deviceService.getDeviceHash();
    final deviceId = await _deviceService.getDeviceId();

    unawaited(_loadLeaderSession());

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
        _latestReport = reports.isEmpty ? null : reports.first;
      });
    } catch (e) {
      debugPrint('Failed to load profile: $e');
    }
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
          ClipRRect(
            borderRadius: BorderRadius.circular(14),
            child: Image.asset(
              'assets/images/logo.jpeg',
              width: 56,
              height: 56,
              fit: BoxFit.cover,
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

  Future<void> _openLocalLeaderArea() async {
    if (_leaderSessionActive) {
      await Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const LeaderInboxScreen()),
      );
    } else {
      await Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const LeaderLoginScreen()),
      );
    }
    if (mounted) await _loadLeaderSession();
  }

  Future<void> _leaderLogout() async {
    await _leader.logout();
    if (mounted) await _loadLeaderSession();
  }

  Widget _buildLocalLeaderSection() {
    if (_leaderSessionActive) {
      return Column(
        children: [
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppColors.card,
              border: Border.all(color: AppColors.border),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.verified_user,
                        size: 18, color: AppColors.accent),
                    const SizedBox(width: 8),
                    const Expanded(
                      child: Text(
                        'Local Leader',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    TextButton(
                      onPressed: _leaderLogout,
                      child: const Text('Log out', style: TextStyle(fontSize: 12)),
                    ),
                  ],
                ),
                if (_leaderName != null && _leaderName!.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    _leaderName!,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
                if (_leaderEmail != null && _leaderEmail!.isNotEmpty)
                  Text(
                    _leaderEmail!,
                    style: const TextStyle(fontSize: 11, color: AppColors.muted),
                  ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _openLocalLeaderArea,
                    icon: const Icon(Icons.inbox_outlined, size: 18),
                    label: const Text('Open leader inbox'),
                  ),
                ),
              ],
            ),
          ),
        ],
      );
    }

    return Column(
      children: [
        _menuItem(Icons.verified_user, 'Local Leader Login', _openLocalLeaderArea),
      ],
    );
  }

  Widget _buildMenuItems() {
    return Column(
      children: [
        _buildLocalLeaderSection(),
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
