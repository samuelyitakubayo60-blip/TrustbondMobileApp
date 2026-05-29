import 'package:flutter/material.dart';
import '../config/theme.dart';

class PrivacySecurityScreen extends StatelessWidget {
  const PrivacySecurityScreen({super.key});

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
          title: const Text('Privacy & Security', style: TextStyle(fontSize: 16)),
          backgroundColor: AppColors.bg,
          elevation: 0,
        ),
        body: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 36),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ── Header ───────────────────────────────────────────────
              Center(
                child: Column(
                  children: [
                    const SizedBox(height: 16),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(18),
                      child: Image.asset(
                        'assets/images/logo.jpeg',
                        width: 72,
                        height: 72,
                        fit: BoxFit.cover,
                      ),
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      'Your Privacy is Protected',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      'TrustBond is built on anonymity and security by design.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 12.5, color: AppColors.muted, height: 1.5),
                    ),
                    const SizedBox(height: 24),
                  ],
                ),
              ),

              _section(
                icon: Icons.fingerprint_rounded,
                color: AppColors.accent,
                title: 'Anonymous by Default',
                body:
                    'You never create an account or share your name. TrustBond generates a '
                    'secure anonymous device ID locally on your phone. Your real identity — '
                    'name, phone number, or email — is never stored, transmitted, or shared.',
              ),
              _section(
                icon: Icons.location_on_outlined,
                color: AppColors.accent2,
                title: 'Location Use',
                body:
                    'Your GPS location is used for two purposes only: '
                    '(1) to attach location data to an incident report you submit, routing it '
                    'to the correct local leader in Musanze District; '
                    '(2) to alert you when you are near a known security hotspot. '
                    'Location tracking runs as a background service while the app is open '
                    'and is never uploaded to a server in real time.',
              ),
              _section(
                icon: Icons.lock_outline_rounded,
                color: AppColors.warn,
                title: 'Data Encryption',
                body:
                    'All reports, evidence files, and communications between the app '
                    'and the TrustBond server are encrypted in transit using HTTPS/TLS. '
                    'Evidence stored on the server is accessible only to authorized local '
                    'leaders and system administrators.',
              ),
              _section(
                icon: Icons.verified_user_outlined,
                color: AppColors.ok,
                title: 'Who Sees Your Reports',
                body:
                    'Submitted reports go through an automated AI screening system first. '
                    'Reports that pass screening are forwarded to the assigned local leader '
                    'for your cell or village in Musanze District. '
                    'No one outside of the TrustBond system can access your reports.',
              ),
              _section(
                icon: Icons.delete_outline_rounded,
                color: AppColors.muted,
                title: 'Data Retention',
                body:
                    'Report data is retained for as long as required to support '
                    'the investigation and follow-up process. Anonymous device IDs '
                    'are retained to maintain trust scoring and prevent abuse. '
                    'No personal identity data is ever collected, so there is '
                    'nothing personally identifiable to delete.',
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _section({
    required IconData icon,
    required Color color,
    required String title,
    required String body,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Container(
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
                color: color.withValues(alpha: 0.10),
                borderRadius: BorderRadius.circular(9),
              ),
              child: Icon(icon, size: 18, color: color),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: const TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.text)),
                  const SizedBox(height: 6),
                  Text(body,
                      style: const TextStyle(
                          fontSize: 12.5,
                          color: AppColors.muted,
                          height: 1.65)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
