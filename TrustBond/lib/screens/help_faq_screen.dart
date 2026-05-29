import 'package:flutter/material.dart';
import '../config/theme.dart';

class HelpFaqScreen extends StatelessWidget {
  const HelpFaqScreen({super.key});

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
          title: const Text('Help & FAQ', style: TextStyle(fontSize: 16)),
          backgroundColor: AppColors.bg,
          elevation: 0,
        ),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 36),
          children: [
            // ── Header ─────────────────────────────────────────────────
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
                    'How can we help?',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                      color: AppColors.text,
                    ),
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Frequently asked questions about TrustBond.',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 12.5, color: AppColors.muted),
                  ),
                  const SizedBox(height: 24),
                ],
              ),
            ),

            // ── FAQs ────────────────────────────────────────────────────
            _faq(
              'What is TrustBond?',
              'TrustBond is a secure, anonymous incident reporting app for citizens '
              'of Musanze District, Rwanda. It lets you report safety incidents directly '
              'from your phone. Reports are screened by an AI system and forwarded to '
              'the assigned local leader in your cell or village.',
            ),
            _faq(
              'Do I need to create an account?',
              'No. TrustBond requires no registration, email address, or password. '
              'The app generates a secure anonymous device ID automatically when you '
              'first open it. This ID is used only to track your report history and '
              'trust score — it cannot be linked back to your identity.',
            ),
            _faq(
              'What happens after I submit a report?',
              'Your report goes through three stages:\n'
              '1. AI Screening — the system checks the report and any attached evidence for authenticity.\n'
              '2. Leader Review — if the report passes screening, it is sent to the local leader assigned to your area.\n'
              '3. Verification — the leader confirms or rejects the report and the status updates in "My Reports".',
            ),
            _faq(
              'Why was my report rejected or flagged?',
              'Common reasons include: the incident location is outside Musanze District, '
              'the attached photo or video appears to be a screenshot or heavily edited, '
              'the report description does not match the evidence, or similar reports '
              'were already submitted from the same location.',
            ),
            _faq(
              'Can anyone identify me from my report?',
              'No. The system only stores a mathematical hash of your device — '
              'not your name, phone number, or any personal detail. '
              'Local leaders can see the incident details and location, but never who submitted it.',
            ),
            _faq(
              'How do safety alerts work?',
              'TrustBond monitors your GPS location in the background while the app is open. '
              'If you come within your selected alert distance of a known security hotspot '
              '(high or critical risk), the app sends you a local notification immediately. '
              'You can change the alert distance on the Safety Map screen.',
            ),
            _faq(
              'Why is there a "Safety Monitoring Active" notification?',
              'This notification means TrustBond is actively tracking your location to watch '
              'for nearby security hotspots. It is required by Android to keep the GPS service '
              'running in the background. You can dismiss it by closing the app entirely.',
            ),
            _faq(
              'What if I lose internet connection?',
              'Reports you submit while offline are saved locally and automatically sent '
              'to the server as soon as your connection is restored. You will see a '
              '"queued" status on the report until it has been successfully uploaded.',
            ),
            _faq(
              'Is this app for emergencies?',
              'TrustBond is not a guaranteed emergency response service. '
              'If you are in immediate danger, contact official emergency services directly. '
              'TrustBond is a reporting tool to help local leaders respond to safety '
              'patterns in the community.',
            ),
          ],
        ),
      ),
    );
  }

  Widget _faq(String question, String answer) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.border),
        ),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
          title: Text(
            question,
            style: const TextStyle(
              fontSize: 13.5,
              fontWeight: FontWeight.w600,
              color: AppColors.text,
            ),
          ),
          collapsedIconColor: AppColors.muted,
          iconColor: AppColors.accent,
          shape: const Border(),
          collapsedShape: const Border(),
          children: [
            Text(
              answer,
              style: const TextStyle(
                fontSize: 13,
                color: AppColors.muted,
                height: 1.65,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
