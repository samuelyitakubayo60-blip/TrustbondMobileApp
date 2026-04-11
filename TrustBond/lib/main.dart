import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'config/theme.dart';
import 'screens/main_shell.dart';
import 'screens/splash_screen.dart';
import 'services/offline_integration_guide.dart';


void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  // Initialize SQLite FFI for desktop platforms
  if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
    try {
      // Initialize FFI first
      sqfliteFfiInit();
      // Then set the database factory
      databaseFactory = databaseFactoryFfi;
      print('SQLite FFI initialized successfully for desktop platform');
    } catch (e) {
      print('SQLite FFI initialization failed: $e');
      print('This is a known issue with SQLite FFI on Windows desktop');
      print('The app will continue with online-only functionality for now');
      // Don't set databaseFactory if FFI fails
    }
  }
  
  // Initialize the offline reporting system
  try {
    await OfflineReportingIntegration().initialize();
    print('Offline reporting system initialized successfully');
  } catch (e) {
    print('Offline system initialization failed: $e');
    print('Continuing without offline features');
    // Continue with app startup even if offline system fails
  }
  
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

        return snapshot.data! ? const SplashScreen() : const MainShell();
      },
    );
  }
}
