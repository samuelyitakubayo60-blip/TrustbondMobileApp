import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import 'main_shell.dart';

class OnboardingScreen extends StatelessWidget {
  const OnboardingScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            // Scrollable content
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                child: Column(
                  children: [
                    const StepIndicators(total: 3, current: 1),
                    const SizedBox(height: 18),
                    // Logo
                    ClipRRect(
                      borderRadius: BorderRadius.circular(24),
                      child: Image.asset(
                        'assets/images/logo.jpeg',
                        width: 90,
                        height: 90,
                        fit: BoxFit.cover,
                      ),
                    ),
                    const SizedBox(height: 16),
                    RichText(
                      textAlign: TextAlign.center,
                      text: const TextSpan(
                        style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                        children: [
                          TextSpan(text: 'Speak Up. ', style: TextStyle(color: AppColors.text)),
                          TextSpan(text: 'Stay Protected', style: TextStyle(color: AppColors.accent)),
                        ],
                      ),
                    ),
                    const SizedBox(height: 10),
                    const Padding(
                      padding: EdgeInsets.symmetric(horizontal: 8),
                      child: Text(
                        'Report safely and confidently. We never collect your name, '
                        'phone number, or personal identity. Your device generates a '
                        'secure anonymous ID — so your voice is heard, not your identity.',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: 12, color: AppColors.muted, height: 1.8),
                      ),
                    ),
                    const SizedBox(height: 22),
                    _buildCard(),
                  ],
                ),
              ),
            ),
            // Bottom actions
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 36),
              child: Column(
                children: [
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: () => Navigator.of(context).pushReplacement(
                        MaterialPageRoute(builder: (_) => const MainShell()),
                      ),
                      child: const Text('Continue →'),
                    ),
                  ),
                  const SizedBox(height: 14),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton(
                      onPressed: () => Navigator.of(context).pop(),
                      child: const Text('← Back'),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildCard() {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(22),
      ),
      child: Column(
        children: [
          _featureRow(
            Icons.fingerprint_rounded,
            AppColors.accent,
            'Anonymous by Design',
            'Your secure device ID is created locally and never connected to your real-world identity.',
          ),
          const SizedBox(height: 16),
          _featureRow(
            Icons.flash_on_rounded,
            AppColors.accent2,
            'No Sign-Up. No Barriers.',
            'No email. No password. No forms. Just open the app and report instantly.',
          ),
          const SizedBox(height: 16),
          _featureRow(
            Icons.verified_user_rounded,
            AppColors.warn,
            'Smart & Responsible Reporting',
            'Advanced AI screens submissions for accuracy before forwarding them — protecting both reporters and authorities.',
          ),
        ],
      ),
    );
  }

  Widget _featureRow(IconData icon, Color color, String title, String subtitle) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Icon(icon, size: 18, color: color),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
              const SizedBox(height: 3),
              Text(subtitle,
                  style: const TextStyle(fontSize: 11, color: AppColors.muted, height: 1.6)),
            ],
          ),
        ),
      ],
    );
  }
}
