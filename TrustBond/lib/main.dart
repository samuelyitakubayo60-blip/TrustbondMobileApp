import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'config/theme.dart';
import 'firebase_options.dart';
import 'screens/biometric_gate.dart';
import 'screens/main_shell.dart';
import 'screens/splash_screen.dart';
import 'services/platform_service.dart';
import 'services/notification_service.dart';

Future<void> _bootstrapNotifications() async {
  // FCM push is mobile-only (Android/iOS). Police use the web dashboard.
  if (PlatformService.supportsFirebase) {
    await Firebase.initializeApp(
      options: DefaultFirebaseOptions.currentPlatform,
    );
    await NotificationService().initialize();
    return;
  }

  // Windows desktop links firebase_core; initialize once so plugins do not throw
  // [core/no-app]. No FCM registration or messaging on desktop.
  if (PlatformService.isDesktop) {
    try {
      await Firebase.initializeApp(
        options: DefaultFirebaseOptions.windows,
      );
    } catch (e) {
      debugPrint('Firebase desktop init (no FCM): $e');
    }
  }
  await MockNotificationService.initialize();
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await _bootstrapNotifications();

  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
      systemNavigationBarColor: Color(0xFF080C18),
    ),
  );
  runApp(const TrustBondApp());
}

class TrustBondApp extends StatelessWidget {
  const TrustBondApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TrustBond',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: const _StartupGate(),
    );
  }
}

class _StartupGate extends StatefulWidget {
  const _StartupGate();

  @override
  State<_StartupGate> createState() => _StartupGateState();
}

class _StartupGateState extends State<_StartupGate> {
  static const _hasSeenSplashKey = 'has_seen_splash_once';
  late final Future<bool> _shouldShowSplashFuture;

  @override
  void initState() {
    super.initState();
    _shouldShowSplashFuture = _shouldShowSplash();
  }

  Future<bool> _shouldShowSplash() async {
    final prefs = await SharedPreferences.getInstance();
    final hasSeenSplash = prefs.getBool(_hasSeenSplashKey) ?? false;
    if (!hasSeenSplash) {
      await prefs.setBool(_hasSeenSplashKey, true);
      return true;
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<bool>(
      future: _shouldShowSplashFuture,
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        return snapshot.data!
            ? const SplashScreen()
            : const BiometricGate(child: MainShell());
      },
    );
  }
}
