import 'package:flutter/material.dart';
import '../config/theme.dart';

class PrivacySecurityScreen extends StatelessWidget {
  const PrivacySecurityScreen({super.key});

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
        title: const Text('Privacy & Security', style: TextStyle(fontSize: 16)),
        backgroundColor: AppColors.surface,
        elevation: 0,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.security, size: 48, color: AppColors.accent),
            const SizedBox(height: 24),
            const Text(
              'Your Data is Protected',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            _buildSection(
              'Anonymity First',
              'Reports are submitted anonymously. We generate a unique device ID to track your trust score without storing your personal identity.',
            ),
            _buildSection(
              'Data Encryption',
              'All evidence and reports are encrypted in transit and at rest. Only authorized personnel can view the details of verified reports.',
            ),
            _buildSection(
              'Location Privacy',
              'We use your location solely to route the report to the correct authorities in the Musanze district. Your real-time location is never tracked continuously.',
            ),
          ],
        ),
      ),
    ),
    );
  }

  Widget _buildSection(String title, String content) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: AppColors.accent2)),
          const SizedBox(height: 8),
          Text(content, style: const TextStyle(fontSize: 14, color: AppColors.muted, height: 1.5)),
        ],
      ),
    );
  }
}
