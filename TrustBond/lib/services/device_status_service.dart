import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:battery_plus/battery_plus.dart';

class DeviceStatusService {
  final Connectivity _connectivity = Connectivity();
  final Battery _battery = Battery();

  Future<String?> getNetworkType() async {
    try {
      final result = await _connectivity.checkConnectivity();

      // connectivity_plus >= 6 returns a Set<ConnectivityResult>
      if (result.contains(ConnectivityResult.wifi)) return 'wifi';
      if (result.contains(ConnectivityResult.mobile)) return 'mobile';
      if (result.contains(ConnectivityResult.ethernet)) return 'ethernet';
      if (result.contains(ConnectivityResult.bluetooth)) return 'bluetooth';
      if (result.contains(ConnectivityResult.vpn)) return 'vpn';
      if (result.contains(ConnectivityResult.other)) return 'other';
      return 'none';
    } catch (_) {
      return null;
    }
  }

  Future<double?> getBatteryLevel() async {
    try {
      final level = await _battery.batteryLevel; // 0–100
      return level.toDouble();
    } catch (_) {
      return null;
    }
  }
}

