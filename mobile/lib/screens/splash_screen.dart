import 'package:flutter/material.dart';
import 'home_screen.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    Future.delayed(const Duration(milliseconds: 2500), () {
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const HomeScreen()),
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final primary = Theme.of(context).colorScheme.primary;
    final onPrimary = Theme.of(context).colorScheme.onPrimary;
    return Scaffold(
      body: Container(
        width: double.infinity,
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              primary,
              primary.withOpacity(0.85),
            ],
          ),
        ),
        child: SafeArea(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Spacer(flex: 2),
              // Logo: use asset if present, otherwise shield icon
              _buildLogo(context, onPrimary),
              const SizedBox(height: 24),
              Text(
                'TrustBond',
                style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                      color: onPrimary,
                      fontWeight: FontWeight.bold,
                    ) ??
                    const TextStyle(
                      fontSize: 32,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
              ),
              const SizedBox(height: 8),
              Text(
                'Report incidents in Musanze',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: onPrimary.withOpacity(0.9),
                    ) ??
                    TextStyle(
                      fontSize: 14,
                      color: Colors.white.withOpacity(0.9),
                    ),
              ),
              const Spacer(flex: 2),
              const Padding(
                padding: EdgeInsets.only(bottom: 32),
                child: SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation<Color>(Colors.white70),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildLogo(BuildContext context, Color color) {
    try {
      return Image.asset(
        'assets/images/logo.jpeg',
        height: 96,
        width: 96,
        fit: BoxFit.contain,
        errorBuilder: (_, __, ___) => Icon(
          Icons.shield_outlined,
          size: 96,
          color: color,
        ),
      );
    } catch (_) {
      return Icon(Icons.shield_outlined, size: 96, color: color);
    }
  }
}
