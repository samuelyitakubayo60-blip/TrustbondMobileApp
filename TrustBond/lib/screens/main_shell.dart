import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config/theme.dart';
import '../services/api_service.dart';
import '../services/device_service.dart';
import '../services/offline_report_queue_service.dart';
import '../services/proximity_alert_service.dart';
import '../services/storage_service.dart';
import 'home_screen.dart';
import 'safety_map_screen.dart';
import 'report_step1_screen.dart';
import 'my_reports_screen.dart';
import 'profile_screen.dart';

/// Main navigation shell with 5-tab bottom nav.
class MainShell extends StatefulWidget {
  final int initialIndex;

  const MainShell({super.key, this.initialIndex = 0});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> with WidgetsBindingObserver {
  late int _currentIndex;
  final _apiService = ApiService();
  final _deviceService = DeviceService();
  final _queueService = OfflineReportQueueService();
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  bool _wasOffline = false;
  bool _biometricLocked = false;
  final _storageService = StorageService();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _currentIndex = widget.initialIndex;
    _bootstrap();
    WidgetsBinding.instance.addPostFrameCallback((_) => _applyBiometricLockIfNeeded());
  }

  Future<void> _bootstrap() async {
    await _ensureDeviceRegistered();
    _startConnectivityWatcher();
    unawaited(_warmOfflineCaches());
    unawaited(_queueService.scheduleSync(reason: 'startup'));
    unawaited(ProximityAlertService().start());
  }

  Future<void> _warmOfflineCaches() async {
    try {
      await _apiService.getIncidentTypes();
    } catch (_) {
      // Cache warmup is best effort.
    }

    try {
      final deviceId = await _deviceService.getDeviceId();
      if (deviceId != null && deviceId.isNotEmpty) {
        await _apiService.getMyReports(deviceId);
      }
    } catch (_) {
      // Cache warmup is best effort.
    }
  }

  Future<void> _ensureDeviceRegistered() async {
    final deviceService = DeviceService();
    final existing = await deviceService.getDeviceId();
    if (existing != null && existing.isNotEmpty) return;
    try {
      final hash = await deviceService.getDeviceHash();
      final result = await ApiService().registerDevice(hash);
      final id = result['device_id']?.toString();
      if (id != null && id.isNotEmpty) {
        await deviceService.saveDeviceId(id);
      }
    } catch (_) {
      // Will retry on next app launch
    }
  }

  void _startConnectivityWatcher() {
    _connectivitySub?.cancel();
    _connectivitySub = Connectivity().onConnectivityChanged.listen((results) {
      final offline = results.contains(ConnectivityResult.none);
      if (_wasOffline && !offline) {
        unawaited(_queueService.scheduleSync(reason: 'connectivity'));
      }
      _wasOffline = offline;
    });
  }

  Future<bool> _isBiometricUnlockEnabled() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool('biometric_auth') ?? false;
  }

  Future<void> _applyBiometricLockIfNeeded() async {
    if (!await _isBiometricUnlockEnabled()) return;
    if (!mounted) return;
    setState(() => _biometricLocked = true);
    final ok = await _storageService.authenticateWithBiometrics(
      reason: 'Unlock TrustBond',
    );
    if (!mounted) return;
    setState(() => _biometricLocked = !ok);
  }

  Future<void> _unlockWithBiometrics() async {
    final ok = await _storageService.authenticateWithBiometrics(
      reason: 'Unlock TrustBond',
    );
    if (!mounted) return;
    if (ok) {
      setState(() => _biometricLocked = false);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(_queueService.scheduleSync(reason: 'resume'));
      unawaited(_applyBiometricLockIfNeeded());
      // Re-check proximity on resume so alerts fire immediately when user
      // returns to the app rather than waiting for the next 60-second poll.
      unawaited(ProximityAlertService().resume());
    }
  }

  void _onTabTapped(int index) {
    if (index == 2) {
      // Center FAB — open report flow
      Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const ReportStep1Screen()),
      );
      return;
    }
    setState(() => _currentIndex = index);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _connectivitySub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      HomeScreen(
        onOpenMapTab: () {
          setState(() => _currentIndex = 1);
        },
      ),
      const SafetyMapScreen(),
      // index 2 is the FAB, not a tab
      const MyReportsScreen(),
      const ProfileScreen(),
    ];

    return Scaffold(
      body: Stack(
        children: [
          IndexedStack(
            index: _currentIndex > 2 ? _currentIndex - 1 : _currentIndex,
            children: pages,
          ),
          if (_biometricLocked) _buildBiometricLockOverlay(),
        ],
      ),
      bottomNavigationBar: _biometricLocked ? null : _buildBottomNav(),
    );
  }

  Widget _buildBiometricLockOverlay() {
    return Positioned.fill(
      child: Material(
        color: const Color(0xF0080C18),
        child: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.fingerprint_rounded,
                    size: 64,
                    color: AppColors.accent,
                  ),
                  const SizedBox(height: 20),
                  const Text(
                    'TrustBond is locked',
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Use fingerprint or face ID to continue',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 14,
                      color: Colors.white.withValues(alpha: 0.7),
                    ),
                  ),
                  const SizedBox(height: 28),
                  FilledButton.icon(
                    onPressed: _unlockWithBiometrics,
                    icon: const Icon(Icons.lock_open_rounded),
                    label: const Text('Unlock'),
                    style: FilledButton.styleFrom(
                      backgroundColor: AppColors.accent,
                      foregroundColor: Colors.black,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 28,
                        vertical: 14,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildBottomNav() {
    return Container(
      decoration: const BoxDecoration(
        color: Color(0xF7080C18),
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: SafeArea(
        child: SizedBox(
          height: 60,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _navItem(0, Icons.home_rounded, 'Home'),
              _navItem(1, Icons.map_rounded, 'Map'),
              _fabItem(),
              _navItem(3, Icons.assignment_outlined, 'My Reports'),
              _navItem(4, Icons.person_outline_rounded, 'Profile'),
            ],
          ),
        ),
      ),
    );
  }

  Widget _navItem(int index, IconData icon, String label) {
    final isActive = _currentIndex == index;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => _onTabTapped(index),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: isActive ? AppColors.accent.withValues(alpha: 0.08) : Colors.transparent,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 22, color: isActive ? AppColors.accent : AppColors.muted),
            const SizedBox(height: 3),
            Text(
              label,
              style: TextStyle(
                fontSize: 9,
                color: isActive ? AppColors.accent : AppColors.muted,
                letterSpacing: 0.4,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _fabItem() {
    // Same icon size (22) and label style as other nav items for a consistent, professional look
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => _onTabTapped(2),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(
                color: AppColors.accent,
                borderRadius: BorderRadius.circular(12),
                boxShadow: [
                  BoxShadow(
                    color: AppColors.accent.withValues(alpha: 0.35),
                    blurRadius: 8,
                    offset: const Offset(0, 2),
                  ),
                ],
              ),
              child: const Icon(Icons.add_rounded, color: Colors.white, size: 22),
            ),
            const SizedBox(height: 3),
            const Text(
              'Report',
              style: TextStyle(fontSize: 9, color: AppColors.muted, letterSpacing: 0.4),
            ),
          ],
        ),
      ),
    );
  }
}
