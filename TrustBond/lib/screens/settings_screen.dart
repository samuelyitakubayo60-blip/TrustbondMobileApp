import 'package:flutter/material.dart';
import '../config/theme.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _anonymousMode = true;
  bool _locationSharing = true;
  bool _dataEncryption = true;
  bool _pushNotif = true;
  bool _hotspotAlerts = true;
  bool _reportUpdates = true;

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildAppBar(),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                children: [
                  _section('Privacy'),
                  _toggle('Anonymous Mode', 'Hide all personal identifiers',
                      _anonymousMode, (v) => setState(() => _anonymousMode = v)),
                  _toggle('Location Sharing', 'Share GPS when submitting reports',
                      _locationSharing, (v) => setState(() => _locationSharing = v)),
                  _toggle('Data Encryption', 'End-to-end encrypt report data',
                      _dataEncryption, (v) => setState(() => _dataEncryption = v)),
                  _section('Notifications'),
                  _toggle('Push Notifications', 'Report status updates',
                      _pushNotif, (v) => setState(() => _pushNotif = v)),
                  _toggle('Hotspot Alerts', 'New danger zone notifications',
                      _hotspotAlerts, (v) => setState(() => _hotspotAlerts = v)),
                  _toggle('Report Updates', 'When your report status changes',
                      _reportUpdates, (v) => setState(() => _reportUpdates = v)),
                  _section('About'),
                  _infoRow('Version', '2.1.0'),
                  _infoRow('Build', '2024.12.01'),
                  _infoRow('AI Model', 'TrustNet v3.2'),
                  const SizedBox(height: 24),
                  _buildDangerActions(),
                  const SizedBox(height: 32),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
    );
  }

  Widget _buildAppBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 20, 4),
      child: Row(
        children: [
          IconButton(
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.chevron_left, size: 28),
          ),
          const Expanded(
            child: Text('Settings',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }

  Widget _section(String title) {
    return Padding(
      padding: const EdgeInsets.only(top: 20, bottom: 8),
      child: Text(title,
          style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppColors.muted,
              letterSpacing: 0.5)),
    );
  }

  Widget _toggle(String title, String sub, bool value, ValueChanged<bool> onChanged) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(
                        fontSize: 13, fontWeight: FontWeight.w600)),
                Text(sub,
                    style:
                        const TextStyle(fontSize: 10, color: AppColors.muted)),
              ],
            ),
          ),
          Switch(
            value: value,
            onChanged: onChanged,
            activeThumbColor: AppColors.accent,
            activeTrackColor: AppColors.accent.withValues(alpha: 0.3),
            inactiveThumbColor: AppColors.muted,
            inactiveTrackColor: AppColors.surface3,
          ),
        ],
      ),
    );
  }

  Widget _infoRow(String label, String value) {
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Text(label,
              style: const TextStyle(fontSize: 12, color: AppColors.muted)),
          const Spacer(),
          Text(value,
              style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  fontFamily: 'monospace')),
        ],
      ),
    );
  }

  Widget _buildDangerActions() {
    return Column(
      children: [
        SizedBox(
          width: double.infinity,
          height: 44,
          child: OutlinedButton.icon(
            onPressed: () {},
            icon: const Icon(Icons.download, size: 16),
            label: const Text('Export My Data',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
            style: OutlinedButton.styleFrom(
              side: const BorderSide(color: AppColors.border),
              foregroundColor: AppColors.text,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12)),
            ),
          ),
        ),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          height: 44,
          child: OutlinedButton.icon(
            onPressed: () => _showClearDialog(),
            icon: const Icon(Icons.delete_outline, size: 16),
            label: const Text('Clear All Data',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
            style: OutlinedButton.styleFrom(
              side: const BorderSide(color: AppColors.danger),
              foregroundColor: AppColors.danger,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12)),
            ),
          ),
        ),
      ],
    );
  }

  void _showClearDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Clear All Data?',
            style: TextStyle(fontWeight: FontWeight.w700)),
        content: const Text(
          'This will erase all local data including your device identity. This cannot be undone.',
          style: TextStyle(fontSize: 13, color: AppColors.muted),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Cancel',
                style: TextStyle(color: AppColors.muted)),
          ),
          TextButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              // TODO: implement clear
            },
            child: const Text('Clear',
                style: TextStyle(color: AppColors.danger)),
          ),
        ],
      ),
    );
  }
}
