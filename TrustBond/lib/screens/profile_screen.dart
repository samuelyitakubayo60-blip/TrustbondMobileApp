import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../services/device_service.dart';
import '../services/api_service.dart';
import '../models/report_model.dart';
import 'settings_screen.dart';
import 'privacy_security_screen.dart';
import 'help_faq_screen.dart';
import 'about_screen.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  String _deviceHashShort = '...';
  int _totalReports = 0;
  int _verifiedReports = 0;
  double _trustScore = 0;
  Map<String, bool>? _achievements;
  bool _isBlacklisted = false;
  String? _blacklistReason;
  String? _lastSeenAt;
  int _spamFlags = 0;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  String _formatLastSeen(String iso) {
    final dt = DateTime.tryParse(iso);
    if (dt == null) return 'Last active: —';
    final diff = DateTime.now().difference(dt);
    if (diff.inMinutes < 60) return 'Last active: ${diff.inMinutes}m ago';
    if (diff.inHours < 24) return 'Last active: ${diff.inHours}h ago';
    if (diff.inDays < 7) return 'Last active: ${diff.inDays}d ago';
    return 'Last active: ${dt.month}/${dt.day}';
  }

  Future<void> _loadData() async {
    // Use anonymous device hash (legacy-compatible with backend).
    final hash = await DeviceService().getDeviceHash();
    if (hash.isEmpty) return;

    setState(() {
      _deviceHashShort = hash.length >= 12
          ? '${hash.substring(0, 8)}...${hash.substring(hash.length - 4)}'
          : hash;
    });

    try {
      final profile = await ApiService().getDeviceProfile(hash);
      setState(() {
        _totalReports = (profile['total_reports'] as num?)?.toInt() ?? 0;
        _verifiedReports =
            (profile['trusted_reports'] as num?)?.toInt() ?? 0;
        _trustScore =
            (profile['device_trust_score'] as num?)?.toDouble() ?? 50.0;
        final a = profile['achievements'] as Map<String, dynamic>?;
        _achievements = a != null
            ? Map<String, bool>.from(a.map((k, v) => MapEntry(k, v == true)))
            : null;
        _isBlacklisted = profile['is_blacklisted'] as bool? ?? false;
        _blacklistReason = profile['blacklist_reason'] as String?;
        _lastSeenAt = profile['last_seen_at'] as String?;
        _spamFlags = (profile['spam_flags'] as num?)?.toInt() ?? 0;
      });
    } catch (e) {
      debugPrint('Failed to load profile: $e');
    }
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
              _buildTrustBreakdown(),
              const SizedBox(height: 14),
              _buildAchievements(),
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
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Anonymous Reporter',
                    style:
                        TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                const SizedBox(height: 2),
                Row(
                  children: [
                    const Text('Device: ',
                        style:
                            TextStyle(fontSize: 11, color: AppColors.muted)),
                    Text(
                      _deviceHashShort,
                      style: const TextStyle(
                          fontSize: 11,
                          fontFamily: 'monospace',
                          color: AppColors.accent),
                    ),
                  ],
                ),
                if (_lastSeenAt != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    _formatLastSeen(_lastSeenAt!),
                    style: const TextStyle(fontSize: 10, color: AppColors.muted),
                  ),
                ],
                const SizedBox(height: 4),
                _isBlacklisted
                    ? StatusBadge(
                        label: _blacklistReason ?? 'Under review',
                        type: BadgeType.warn,
                      )
                    : StatusBadge(label: 'Verified Device', type: BadgeType.ok),
                if (_spamFlags > 0)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                      'Spam flags: $_spamFlags',
                      style: const TextStyle(fontSize: 10, color: AppColors.warn),
                    ),
                  ),
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
        Expanded(child: StatBox(value: '$_totalReports', label: 'Reports', valueColor: AppColors.accent)),
        const SizedBox(width: 9),
        Expanded(child: StatBox(value: '${_trustScore.toInt()}', label: 'Trust Score', valueColor: AppColors.accent2)),
        const SizedBox(width: 9),
        Expanded(child: StatBox(value: '$_verifiedReports', label: 'Verified', valueColor: AppColors.ok)),
      ],
    );
  }

  Widget _buildTrustBreakdown() {
    final quality = _totalReports > 0
        ? (_verifiedReports / _totalReports).clamp(0.0, 1.0)
        : 0.0;
    final score = (_trustScore / 100).clamp(0.0, 1.0);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Trust Score Breakdown',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
          const SizedBox(height: 14),
          _trustBar('Report Quality', quality, AppColors.accent),
          _trustBar('Verification Rate', score, AppColors.accent2),
          _trustBar('Total Reports', (_totalReports / 20).clamp(0.0, 1.0), AppColors.ok),
          _trustBar('Consistency', _totalReports > 0 ? 0.6 + (quality * 0.4) : 0.0, AppColors.warn),
        ],
      ),
    );
  }

  Widget _trustBar(String label, double value, Color color) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                  child: Text(label,
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.muted))),
              Text('${(value * 100).toInt()}%',
                  style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: color)),
            ],
          ),
          const SizedBox(height: 5),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: value,
              backgroundColor: AppColors.surface3,
              valueColor: AlwaysStoppedAnimation(color),
              minHeight: 5,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAchievements() {
    // Prefer backend/ML achievements when available; fallback to local logic
    final a = _achievements;
    final badges = [
      _Badge('🛡️', 'First Report', a?['first_report'] ?? _totalReports >= 1),
      _Badge('⭐', '5 Verified', a?['five_verified'] ?? _verifiedReports >= 5),
      _Badge('🏆', '10 Reports', a?['ten_reports'] ?? _totalReports >= 10),
      _Badge('🔥', 'Streak x7', a?['streak_x7'] ?? _totalReports >= 7),
      _Badge('💎', 'Top Reporter', a?['top_reporter'] ?? _totalReports >= 20),
    ];
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Achievements',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: badges.map((b) {
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 48,
                    height: 48,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: b.unlocked
                          ? AppColors.accent.withValues(alpha: 0.1)
                          : AppColors.surface3,
                      border: Border.all(
                          color: b.unlocked
                              ? AppColors.accent.withValues(alpha: 0.3)
                              : AppColors.border),
                    ),
                    alignment: Alignment.center,
                    child: Text(b.icon,
                        style: TextStyle(
                            fontSize: 20,
                            color: b.unlocked ? null : AppColors.muted)),
                  ),
                  const SizedBox(height: 4),
                  Text(b.label,
                      style: TextStyle(
                          fontSize: 9,
                          color: b.unlocked
                              ? AppColors.text
                              : AppColors.muted)),
                ],
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildMenuItems() {
    return Column(
      children: [
        _menuItem(Icons.security, 'Privacy & Security', () {
          Navigator.push(context, MaterialPageRoute(builder: (_) => const PrivacySecurityScreen()));
        }),
        _menuItem(Icons.help_outline, 'Help & FAQ', () {
          Navigator.push(context, MaterialPageRoute(builder: (_) => const HelpFaqScreen()));
        }),
        _menuItem(Icons.info_outline, 'About TrustBond', () {
          Navigator.push(context, MaterialPageRoute(builder: (_) => const AboutScreen()));
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

class _Badge {
  final String icon;
  final String label;
  final bool unlocked;

  _Badge(this.icon, this.label, this.unlocked);
}
