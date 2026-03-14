import 'package:flutter/material.dart';
import '../config/theme.dart';

class HelpFaqScreen extends StatelessWidget {
  const HelpFaqScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.chevron_left),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: const Text('Help & FAQ', style: TextStyle(fontSize: 16)),
        backgroundColor: AppColors.surface,
        elevation: 0,
      ),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Text(
            'Frequently Asked Questions',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 24),
          _buildFaqItem(
            'How do I earn a higher trust score?',
            'Your trust score increases as your reports are verified by law enforcement. Submitting accurate evidence (photos/videos) significantly boosts your score.',
          ),
          _buildFaqItem(
            'What happens when I report an incident?',
            'The report is securely transmitted to the nearest station in the Musanze district. Our AI system will quickly scan it for authenticity before assigning it to an officer.',
          ),
          _buildFaqItem(
            'Can the police identify me?',
            'No. The system only sees a mathematical representation of your device (a hash) to track reliability, not your name or phone number.',
          ),
          _buildFaqItem(
            'Why was my report flagged or rejected?',
            'Reports may be rejected if they are outside the service area, lack sufficient evidence, or if the AI detects the photo might be a screenshot or heavily edited.',
          ),
        ],
      ),
    ),
    );
  }

  Widget _buildFaqItem(String question, String answer) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: ExpansionTile(
        title: Text(question, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
        childrenPadding: const EdgeInsets.only(left: 16, right: 16, bottom: 16),
        collapsedIconColor: AppColors.accent,
        iconColor: AppColors.accent2,
        children: [
          Text(answer, style: const TextStyle(fontSize: 13, color: AppColors.muted, height: 1.5)),
        ],
      ),
    );
  }
}
