import 'package:flutter/material.dart';
import '../config/theme.dart';

class AboutScreen extends StatelessWidget {
  const AboutScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
        backgroundColor: AppColors.bg,
        appBar: AppBar(
          leading: IconButton(
            icon: const Icon(Icons.chevron_left),
            onPressed: () => Navigator.of(context).pop(),
          ),
          title: const Text('About TrustBond', style: TextStyle(fontSize: 16)),
          backgroundColor: AppColors.bg,
          elevation: 0,
        ),
        body: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 36),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              const SizedBox(height: 24),

              // ── Logo ────────────────────────────────────────────────
              Container(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: AppColors.accent.withValues(alpha: 0.18),
                      blurRadius: 28,
                      spreadRadius: 4,
                    ),
                  ],
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(26),
                  child: Image.asset(
                    'assets/images/logo.jpeg',
                    width: 100,
                    height: 100,
                    fit: BoxFit.cover,
                  ),
                ),
              ),
              const SizedBox(height: 20),

              const Text(
                'TrustBond',
                style: TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  letterSpacing: -0.3,
                  color: AppColors.text,
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                'Version 1.0.0',
                style: TextStyle(color: AppColors.muted, fontSize: 13),
              ),

              const SizedBox(height: 28),

              // ── Mission card ─────────────────────────────────────────
              _infoCard(
                icon: Icons.flag_outlined,
                title: 'Our Mission',
                body:
                    'TrustBond connects citizens of Musanze District with local leaders '
                    'and authorities through a secure, anonymous incident reporting platform. '
                    'We empower communities to speak up about safety issues without fear, '
                    'while giving leaders the tools to act quickly and transparently.',
              ),
              const SizedBox(height: 12),

              // ── How it works card ────────────────────────────────────
              _infoCard(
                icon: Icons.account_tree_outlined,
                title: 'How It Works',
                body:
                    'Citizens submit incident reports directly from their phone. '
                    'Each report is screened by an AI verification system to assess '
                    'credibility and filter out false submissions. Verified reports are '
                    'forwarded to the assigned local leader for review and action. '
                    'The reporter receives real-time status updates at every stage.',
              ),
              const SizedBox(height: 12),

              // ── Privacy card ─────────────────────────────────────────
              _infoCard(
                icon: Icons.lock_outline_rounded,
                title: 'Privacy & Anonymity',
                body:
                    'No account registration is required. TrustBond generates a secure '
                    'anonymous device identifier locally — your name, phone number, and '
                    'personal details are never stored or shared. Your identity remains '
                    'fully protected throughout the entire reporting process.',
              ),
              const SizedBox(height: 12),

              // ── Coverage card ────────────────────────────────────────
              _infoCard(
                icon: Icons.location_on_outlined,
                title: 'Coverage Area',
                body:
                    'TrustBond currently serves Musanze District, Northern Province, Rwanda. '
                    'The system is designed to scale across sectors, cells, and villages, '
                    'routing each report to the correct local leader based on GPS location.',
              ),

              const SizedBox(height: 32),
              const Divider(color: AppColors.border),
              const SizedBox(height: 16),

              const Text(
                '© 2026 TrustBond Project\nMusanze District, Rwanda',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: AppColors.muted, height: 1.7),
              ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      ),
    );
  }

  Widget _infoCard({
    required IconData icon,
    required String title,
    required String body,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: AppColors.accent.withValues(alpha: 0.10),
              borderRadius: BorderRadius.circular(9),
            ),
            child: Icon(icon, size: 18, color: AppColors.accent),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w700,
                    color: AppColors.text,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  body,
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: AppColors.muted,
                    height: 1.65,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
