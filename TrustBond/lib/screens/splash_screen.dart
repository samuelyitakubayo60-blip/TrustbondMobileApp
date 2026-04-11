import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import 'onboarding_screen.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _fade;
  late final Animation<Offset> _slide;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    );
    _fade = CurvedAnimation(parent: _controller, curve: Curves.easeOutCubic);
    _slide = Tween<Offset>(
      begin: const Offset(0, 0.08),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeOutCubic));
    _controller.forward();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        width: double.infinity,
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(-0.35, -0.7),
            radius: 1.45,
            colors: [Color(0xFF102444), Color(0xFF070D19)],
          ),
        ),
        child: SafeArea(
          child: Stack(
            children: [
              Positioned(
                top: 72,
                right: -35,
                child: Container(
                  width: 150,
                  height: 150,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: AppColors.accent.withValues(alpha: 0.06),
                  ),
                ),
              ),
              Positioned(
                bottom: 120,
                left: -48,
                child: Container(
                  width: 180,
                  height: 180,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: AppColors.accent2.withValues(alpha: 0.08),
                  ),
                ),
              ),
              FadeTransition(
                opacity: _fade,
                child: SlideTransition(
                  position: _slide,
                  child: Column(
                    children: [
                      const Spacer(flex: 2),
                      Container(
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(28),
                          boxShadow: [
                            BoxShadow(
                              color: AppColors.accent.withValues(alpha: 0.22),
                              blurRadius: 30,
                              spreadRadius: 2,
                            ),
                          ],
                        ),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(28),
                          child: Image.asset(
                            'assets/images/logo.jpeg',
                            width: 112,
                            height: 112,
                            fit: BoxFit.cover,
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      RichText(
                        text: const TextSpan(
                          style: TextStyle(
                            fontSize: 30,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 3,
                          ),
                          children: [
                            TextSpan(text: 'TRUST', style: TextStyle(color: AppColors.text)),
                            TextSpan(text: 'BOND', style: TextStyle(color: AppColors.accent)),
                          ],
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'COMMUNITY SAFETY · RWANDA',
                        style: TextStyle(fontSize: 10, color: AppColors.muted, letterSpacing: 2.4),
                      ),
                      const AccentLine(),
                      const Padding(
                        padding: EdgeInsets.symmetric(horizontal: 52),
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
                            Container(
                              width: double.infinity,
                              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                              decoration: BoxDecoration(
                                color: AppColors.surface2.withValues(alpha: 0.8),
                                borderRadius: BorderRadius.circular(14),
                                border: Border.all(color: AppColors.border),
                              ),
                              child: const Row(
                                children: [
                                  Icon(Icons.info_outline, size: 14, color: AppColors.muted),
                                  SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      'First launch requires terms and privacy acceptance.',
                                      style: TextStyle(fontSize: 11, color: AppColors.muted),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            const SizedBox(height: 12),
                            SizedBox(
                              width: double.infinity,
                              child: ElevatedButton(
                                onPressed: () => Navigator.of(context).pushReplacement(
                                  MaterialPageRoute(builder: (_) => const OnboardingScreen()),
                                ),
                                child: const Text('Get Started'),
                              ),
                            ),
                            const SizedBox(height: 12),
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
            ],
          ),
        ),
      ),
    );
  }
}
