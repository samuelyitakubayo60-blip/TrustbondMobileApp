import 'dart:async';
import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../services/api_service.dart';
import '../services/device_service.dart';
import '../services/offline_report_queue.dart';
import '../services/app_refresh_bus.dart';
import 'home_screen.dart';
import 'safety_map_screen.dart';
import 'report_step1_screen.dart';
import 'my_reports_screen.dart';
import 'profile_screen.dart';
import 'package:connectivity_plus/connectivity_plus.dart';

/// Main navigation shell with 5-tab bottom nav.
class MainShell extends StatefulWidget {
  final int initialIndex;

  const MainShell({super.key, this.initialIndex = 0});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  late int _currentIndex;
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  Timer? _queueSyncTimer;
  bool _syncInFlight = false;

  @override
  void initState() {
    super.initState();
    _currentIndex = widget.initialIndex;
    _ensureDeviceRegistered();
    _startOfflineSync();
  }

  /// Register the device with the backend on first launch.
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

  void _startOfflineSync() {
    // Best-effort sync on app start.
    _triggerOfflineSync('sync_startup');

    // Keep retrying while app is open so temporary failures recover automatically.
    _queueSyncTimer = Timer.periodic(const Duration(seconds: 20), (_) {
      _triggerOfflineSync('sync_timer');
    });

    _connectivitySub = Connectivity().onConnectivityChanged.listen((r) async {
      if (!r.contains(ConnectivityResult.none)) {
        await _triggerOfflineSync('sync_connectivity');
      }
    });
  }

  Future<void> _triggerOfflineSync(String reason) async {
    if (_syncInFlight) return;
    _syncInFlight = true;
    try {
      await OfflineReportQueue().syncIfNeeded();
      AppRefreshBus.notify(reason);
    } finally {
      _syncInFlight = false;
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
    _connectivitySub?.cancel();
    _queueSyncTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _currentIndex > 2 ? _currentIndex - 1 : _currentIndex,
        children: const [
          HomeScreen(),
          SafetyMapScreen(),
          // index 2 is the FAB, not a tab
          MyReportsScreen(),
          ProfileScreen(),
        ],
      ),
      bottomNavigationBar: _buildBottomNav(),
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
