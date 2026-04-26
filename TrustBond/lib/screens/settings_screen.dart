import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../config/theme.dart';
import '../services/location_service.dart';
import '../services/notification_service.dart';
import '../services/storage_service.dart';
import '../services/platform_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _locationSharing = true;
  bool _dataEncryption = true;
  bool _biometricAuth = false;
  bool _secureStorage = true;
  bool _autoBackup = false;
  bool _pushNotif = true;
  bool _hotspotAlerts = true;
  bool _reportUpdates = true;
  bool _loading = true;

  final LocationService _locationService = LocationService();
  final StorageService _storageService = StorageService();

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      setState(() {
        _locationSharing = prefs.getBool('location_sharing') ?? true;
        _dataEncryption = prefs.getBool('data_encryption') ?? true;
        _pushNotif = prefs.getBool('push_notifications') ?? true;
        _hotspotAlerts = prefs.getBool('hotspot_alerts') ?? true;
        _reportUpdates = prefs.getBool('report_updates') ?? true;
        _biometricAuth = prefs.getBool('biometric_auth') ?? false;
        _autoBackup = prefs.getBool('auto_backup') ?? true;
        _secureStorage = prefs.getBool('secure_storage') ?? true;
        _loading = false;
      });
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  Future<void> _saveSetting(String key, bool value) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(key, value);
    } catch (e) {
      _showError('Failed to save setting');
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: AppColors.error,
      ),
    );
  }

  void _showSuccess(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: AppColors.success,
      ),
    );
  }

  Future<void> _onLocationSharingChanged(bool value) async {
    if (!value) {
      // Request to disable location sharing
      try {
        await _locationService.disableLocationTracking();
        setState(() => _locationSharing = false);
        await _saveSetting('location_sharing', false);
        _showSuccess('Location sharing disabled');
      } catch (e) {
        _showError('Failed to disable location sharing');
      }
    } else {
      // Request to enable location sharing
      try {
        final granted = await _locationService.requestLocationPermission();
        if (granted) {
          setState(() => _locationSharing = true);
          await _saveSetting('location_sharing', true);
          _showSuccess('Location sharing enabled');
        } else {
          _showError('Location permission denied');
        }
      } catch (e) {
        _showError('Failed to enable location sharing');
      }
    }
  }

  Future<void> _onDataEncryptionChanged(bool value) async {
    try {
      if (value) {
        await _storageService.enableEncryption();
        _showSuccess('Data encryption enabled');
      } else {
        final confirmed = await _showConfirmationDialog(
          'Disable Encryption',
          'Are you sure? This will make your data less secure.',
        );
        if (!confirmed) return;
        await _storageService.disableEncryption();
        _showSuccess('Data encryption disabled');
      }
      setState(() => _dataEncryption = value);
      await _saveSetting('data_encryption', value);
    } catch (e) {
      _showError('Failed to update encryption setting');
    }
  }

  Future<void> _onBiometricAuthChanged(bool value) async {
    try {
      if (value) {
        final available = await _storageService.isBiometricAvailable();
        if (!available) {
          _showError('Biometric authentication not available on this device');
          return;
        }
        final authenticated = await _storageService.authenticateWithBiometrics();
        if (!authenticated) {
          _showError('Biometric authentication failed');
          return;
        }
        _showSuccess('Biometric authentication enabled');
      } else {
        _showSuccess('Biometric authentication disabled');
      }
      setState(() => _biometricAuth = value);
      await _saveSetting('biometric_auth', value);
    } catch (e) {
      _showError('Failed to update biometric authentication');
    }
  }

  Future<void> _onSecureStorageChanged(bool value) async {
    try {
      if (value) {
        await _storageService.enableSecureStorage();
        _showSuccess('Secure storage enabled');
      } else {
        final confirmed = await _showConfirmationDialog(
          'Disable Secure Storage',
          'Are you sure? This will store sensitive data in regular storage.',
        );
        if (!confirmed) return;
        await _storageService.disableSecureStorage();
        _showSuccess('Secure storage disabled');
      }
      setState(() => _secureStorage = value);
      await _saveSetting('secure_storage', value);
    } catch (e) {
      _showError('Failed to update secure storage setting');
    }
  }

  Future<void> _onAutoBackupChanged(bool value) async {
    try {
      if (value) {
        await _storageService.enableAutoBackup();
        _showSuccess('Auto backup enabled');
      } else {
        await _storageService.disableAutoBackup();
        _showSuccess('Auto backup disabled');
      }
      setState(() => _autoBackup = value);
      await _saveSetting('auto_backup', value);
    } catch (e) {
      _showError('Failed to update auto backup setting');
    }
  }

  Future<void> _onPushNotificationsChanged(bool value) async {
    try {
      if (!PlatformService.supportsPushNotifications) {
        _showError('Push notifications not supported on this platform');
        return;
      }
      
      if (value) {
        await NotificationService().enableNotifications();
        _showSuccess('Push notifications enabled');
      } else {
        await NotificationService().disableNotifications();
        _showSuccess('Push notifications disabled');
      }
      setState(() => _pushNotif = value);
      await _saveSetting('push_notifications', value);
    } catch (e) {
      _showError('Failed to update notification settings');
    }
  }

  Future<void> _onHotspotAlertsChanged(bool value) async {
    try {
      if (!PlatformService.supportsPushNotifications) {
        _showError('Hotspot alerts not supported on this platform');
        return;
      }
      
      if (value) {
        await NotificationService().subscribeToTopic('hotspot_alerts');
        _showSuccess('Hotspot alerts enabled');
      } else {
        await NotificationService().unsubscribeFromTopic('hotspot_alerts');
        _showSuccess('Hotspot alerts disabled');
      }
      setState(() => _hotspotAlerts = value);
      await _saveSetting('hotspot_alerts', value);
    } catch (e) {
      _showError('Failed to update hotspot alerts');
    }
  }

  Future<void> _onReportUpdatesChanged(bool value) async {
    try {
      if (!PlatformService.supportsPushNotifications) {
        _showError('Report updates not supported on this platform');
        return;
      }
      
      if (value) {
        await NotificationService().subscribeToTopic('report_updates');
        _showSuccess('Report updates enabled');
      } else {
        await NotificationService().unsubscribeFromTopic('report_updates');
        _showSuccess('Report updates disabled');
      }
      setState(() => _reportUpdates = value);
      await _saveSetting('report_updates', value);
    } catch (e) {
      _showError('Failed to update report updates');
    }
  }

  Future<bool> _showConfirmationDialog(String title, String message) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Confirm'),
          ),
        ],
      ),
    );
    return result ?? false;
  }

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
                child: _loading
                    ? const Center(child: CircularProgressIndicator(color: AppColors.accent))
                    : ListView(
                        padding: const EdgeInsets.symmetric(horizontal: 24),
                        children: [
                          _section('Privacy & Security'),
                          _toggle('Location Sharing', 'Share GPS when submitting reports',
                              _locationSharing, _onLocationSharingChanged),
                          _toggle('Data Encryption', 'End-to-end encrypt report data',
                              _dataEncryption, _onDataEncryptionChanged),
                          _toggle('Biometric Authentication', 'Use fingerprint or face ID to unlock',
                              _biometricAuth, _onBiometricAuthChanged),
                          _toggle('Secure Storage', 'Store sensitive data in encrypted local storage',
                              _secureStorage, _onSecureStorageChanged),
                          _toggle('Auto Backup', 'Automatically backup encrypted reports to secure cloud',
                              _autoBackup, _onAutoBackupChanged),
                          _section('Notifications'),
                          _toggle('Push Notifications', 'Report status updates',
                              _pushNotif, _onPushNotificationsChanged),
                          _toggle('Hotspot Alerts', 'New danger zone notifications',
                              _hotspotAlerts, _onHotspotAlertsChanged),
                          _toggle('Report Updates', 'When your report status changes',
                              _reportUpdates, _onReportUpdatesChanged),
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

  Widget _toggle(String title, String sub, bool value, Function(bool) onChanged) {
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
            onChanged: (newValue) {
              // Don't block the UI - call the async function
              onChanged(newValue);
            },
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
