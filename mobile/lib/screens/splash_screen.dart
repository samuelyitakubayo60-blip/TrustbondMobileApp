import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import 'onboarding_screen.dart';

class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        width: double.infinity,
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(-0.4, -0.6),
            radius: 1.4,
            colors: [Color(0xFF0D1A2E), Color(0xFF060B14)],
          ),
        ),
        child: SafeArea(
          child: Column(
            children: [
              const Spacer(flex: 2),
              ClipRRect(
                borderRadius: BorderRadius.circular(28),
                child: Image.asset(
                  'assets/images/logo.jpeg',
                  width: 110,
                  height: 110,
                  fit: BoxFit.cover,
                ),
              ),
              const SizedBox(height: 16),
              RichText(
                text: const TextSpan(
                  style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: 3),
                  children: [
                    TextSpan(text: 'TRUST', style: TextStyle(color: AppColors.text)),
                    TextSpan(text: 'BOND', style: TextStyle(color: AppColors.accent)),
                  ],
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'COMMUNITY SAFETY · RWANDA',
                style: TextStyle(fontSize: 10, color: AppColors.muted, letterSpacing: 2.5),
              ),
              const AccentLine(),
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 60),
                child: Text(
                  'Anonymous reporting. Intelligent verification. Safer Musanze.',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 12, color: AppColors.muted, height: 1.8),
                ),
              ),
              const Spacer(flex: 2),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 36),
                child: Column(
                  children: [
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: () => Navigator.of(context).pushReplacement(
                          MaterialPageRoute(builder: (_) => const OnboardingScreen()),
                        ),
                        child: const Text('Get Started →'),
                      ),
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      'Your identity is always protected',
                      style: TextStyle(fontSize: 10, color: AppColors.muted),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
