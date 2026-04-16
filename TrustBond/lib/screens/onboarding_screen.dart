import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../config/theme.dart';
import '../widgets/shared_widgets.dart';
import '../services/location_service.dart';
import 'main_shell.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen>
    with SingleTickerProviderStateMixin {
  static const String _legalAcceptedKey = 'has_accepted_terms_and_privacy';

  bool _acceptedTerms = false;
  bool _isContinuing = false;
  bool _termsRead = false;
  bool _privacyRead = false;

  late final AnimationController _fadeController;
  late final Animation<double> _fadeAnimation;

  @override
  void initState() {
    super.initState();
    _loadConsent();

    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 650),
    );
    _fadeAnimation = CurvedAnimation(
      parent: _fadeController,
      curve: Curves.easeOut,
    );
    _fadeController.forward();
  }

  @override
  void dispose() {
    _fadeController.dispose();
    super.dispose();
  }

  Future<void> _loadConsent() async {
    final prefs = await SharedPreferences.getInstance();
    final accepted = prefs.getBool(_legalAcceptedKey) ?? false;
    if (!mounted) return;

    setState(() {
      _acceptedTerms = accepted;
      if (accepted) {
        _termsRead = true;
        _privacyRead = true;
      }
    });
  }

  Future<void> _persistConsent() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_legalAcceptedKey, true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: FadeTransition(
          opacity: _fadeAnimation,
          child: Column(
            children: [
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                  child: Column(
                    children: [
                      const StepIndicators(total: 3, current: 1),
                      const SizedBox(height: 20),
                      _buildHeader(),
                      const SizedBox(height: 24),
                      _buildFeatureCard(),
                      const SizedBox(height: 16),
                      _buildLegalConsentCard(),
                    ],
                  ),
                ),
              ),
              _buildBottomActions(context),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Column(
      children: [
        Container(
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: AppColors.accent.withValues(alpha: 0.18),
                blurRadius: 24,
                spreadRadius: 4,
              ),
            ],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(24),
            child: Image.asset(
              'assets/images/logo.jpeg',
              width: 84,
              height: 84,
              fit: BoxFit.cover,
            ),
          ),
        ),
        const SizedBox(height: 18),
        RichText(
          textAlign: TextAlign.center,
          text: const TextSpan(
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.3),
            children: [
              TextSpan(text: 'Speak Up. ', style: TextStyle(color: AppColors.text)),
              TextSpan(text: 'Stay Protected', style: TextStyle(color: AppColors.accent)),
            ],
          ),
        ),
        const SizedBox(height: 10),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 12),
          child: Text(
            'Your voice matters and your identity stays yours. '
            'TrustBond uses a secure anonymous ID generated on your device, '
            'so you can report safely without fear.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, color: AppColors.muted, height: 1.7),
          ),
        ),
      ],
    );
  }

  Widget _buildFeatureCard() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(22),
      ),
      child: Column(
        children: [
          _featureRow(
            icon: Icons.fingerprint_rounded,
            color: AppColors.accent,
            title: 'Anonymous by Design',
            subtitle:
                'Your ID is generated locally and never linked to your real-world identity, not your name, number, or device model.',
          ),
          _featureDivider(),
          _featureRow(
            icon: Icons.bolt_rounded,
            color: AppColors.accent2,
            title: 'No Sign-Up. No Barriers.',
            subtitle: 'No email, no password, no forms. Open the app and report in seconds.',
          ),
          _featureDivider(),
          _featureRow(
            icon: Icons.verified_user_rounded,
            color: AppColors.warn,
            title: 'AI-Powered Verification',
            subtitle:
                'Every report is screened for accuracy by our intelligent system before reaching authorities, keeping data clean and actionable.',
          ),
        ],
      ),
    );
  }

  Widget _featureDivider() {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: 14),
      child: Divider(
        color: AppColors.border,
        thickness: 1,
        height: 1,
      ),
    );
  }

  Widget _featureRow({
    required IconData icon,
    required Color color,
    required String title,
    required String subtitle,
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: color.withValues(alpha: 0.2)),
          ),
          child: Icon(icon, size: 20, color: color),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
                style: const TextStyle(fontSize: 12, color: AppColors.muted, height: 1.65),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildLegalConsentCard() {
    final bothRead = _termsRead && _privacyRead;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(
          color: _acceptedTerms
              ? AppColors.accent.withValues(alpha: 0.4)
              : AppColors.border,
        ),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.shield_outlined, size: 16, color: AppColors.accent),
              const SizedBox(width: 8),
              const Text(
                'Before You Continue',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            'Please review both documents below before accepting.',
            style: TextStyle(fontSize: 11.5, color: AppColors.muted, height: 1.5),
          ),
          const SizedBox(height: 14),
          _legalDocButton(
            icon: Icons.gavel_rounded,
            label: 'Terms & Conditions',
            isRead: _termsRead,
            onTap: () async {
              final done = await _showLegalSheetRequireFullRead(
                title: 'Terms and Conditions',
                body: _termsAndConditionsText,
              );
              if (!mounted || !done) return;
              setState(() => _termsRead = true);
            },
          ),
          const SizedBox(height: 8),
          _legalDocButton(
            icon: Icons.privacy_tip_outlined,
            label: 'Privacy Policy',
            isRead: _privacyRead,
            onTap: () async {
              final done = await _showLegalSheetRequireFullRead(
                title: 'Privacy Policy',
                body: _privacyPolicyText,
              );
              if (!mounted || !done) return;
              setState(() => _privacyRead = true);
            },
          ),
          const SizedBox(height: 14),
          if (!bothRead)
            const Padding(
              padding: EdgeInsets.only(bottom: 10),
              child: Row(
                children: [
                  Icon(Icons.info_outline, size: 13, color: AppColors.muted),
                  SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Scroll to the end of each document to enable acceptance.',
                      style: TextStyle(fontSize: 11, color: AppColors.muted, height: 1.5),
                    ),
                  ),
                ],
              ),
            ),
          GestureDetector(
            onTap: bothRead ? () => setState(() => _acceptedTerms = !_acceptedTerms) : null,
            child: AnimatedOpacity(
              opacity: bothRead ? 1.0 : 0.45,
              duration: const Duration(milliseconds: 250),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: _acceptedTerms
                      ? AppColors.accent.withValues(alpha: 0.06)
                      : Colors.transparent,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: _acceptedTerms
                        ? AppColors.accent.withValues(alpha: 0.25)
                        : AppColors.border,
                  ),
                ),
                child: Row(
                  children: [
                    SizedBox(
                      width: 22,
                      height: 22,
                      child: Checkbox(
                        value: _acceptedTerms,
                        onChanged: bothRead ? (v) => setState(() => _acceptedTerms = v ?? false) : null,
                        activeColor: AppColors.accent,
                        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        visualDensity: VisualDensity.compact,
                      ),
                    ),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text(
                        'I have read and accept the Terms & Conditions and Privacy Policy.',
                        style: TextStyle(fontSize: 12, color: AppColors.text, height: 1.5),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _legalDocButton({
    required IconData icon,
    required String label,
    required bool isRead,
    required VoidCallback onTap,
  }) {
    return SizedBox(
      width: double.infinity,
      child: OutlinedButton.icon(
        onPressed: onTap,
        icon: Icon(
          isRead ? Icons.check_circle_rounded : icon,
          size: 16,
          color: isRead ? Colors.green : null,
        ),
        label: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label),
            if (isRead)
              Text(
                'Read',
                style: TextStyle(
                  fontSize: 11,
                  color: Colors.green.shade600,
                  fontWeight: FontWeight.w600,
                ),
              )
            else
              const Text(
                'Tap to view',
                style: TextStyle(
                  fontSize: 11,
                  color: AppColors.muted,
                  fontWeight: FontWeight.w400,
                ),
              ),
          ],
        ),
        style: OutlinedButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          side: BorderSide(
            color: isRead ? Colors.green.withValues(alpha: 0.4) : AppColors.border,
          ),
          backgroundColor: isRead ? Colors.green.withValues(alpha: 0.04) : null,
          alignment: Alignment.centerLeft,
        ),
      ),
    );
  }

  Future<bool> _showLegalSheetRequireFullRead({
    required String title,
    required String body,
  }) async {
    final controller = ScrollController();
    bool reachedBottom = false;

    final completed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setSheetState) {
            void refreshBottomState() {
              if (!controller.hasClients) return;
              final canScroll = controller.position.maxScrollExtent > 0;
              final atBottom = !canScroll || controller.position.extentAfter <= 8;
              if (atBottom != reachedBottom) {
                setSheetState(() => reachedBottom = atBottom);
              }
            }

            WidgetsBinding.instance.addPostFrameCallback((_) => refreshBottomState());

            return SafeArea(
              child: SizedBox(
                height: MediaQuery.of(ctx).size.height * 0.82,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(18, 14, 18, 18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Center(
                        child: Container(
                          width: 40,
                          height: 4,
                          decoration: BoxDecoration(
                            color: AppColors.border,
                            borderRadius: BorderRadius.circular(8),
                          ),
                        ),
                      ),
                      const SizedBox(height: 14),
                      Text(
                        title,
                        style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 10),
                      const Divider(),
                      const SizedBox(height: 8),
                      Expanded(
                        child: NotificationListener<ScrollNotification>(
                          onNotification: (_) {
                            refreshBottomState();
                            return false;
                          },
                          child: SingleChildScrollView(
                            controller: controller,
                            child: Text(
                              body,
                              style: const TextStyle(
                                fontSize: 13,
                                color: AppColors.muted,
                                height: 1.8,
                              ),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 8),
                      if (!reachedBottom)
                        const Padding(
                          padding: EdgeInsets.only(bottom: 8),
                          child: Text(
                            'Please scroll to the bottom to continue.',
                            style: TextStyle(fontSize: 11, color: AppColors.muted),
                          ),
                        ),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton(
                          onPressed: reachedBottom
                              ? () => Navigator.of(ctx).pop(true)
                              : null,
                          child: const Text('Done Reading'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );

    controller.dispose();
    return completed ?? false;
  }

  Widget _buildBottomActions(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 36),
      child: Column(
        children: [
          AnimatedOpacity(
            opacity: (_acceptedTerms && !_isContinuing) ? 1.0 : 0.5,
            duration: const Duration(milliseconds: 250),
            child: SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: (_acceptedTerms && !_isContinuing)
                    ? _continueWithLocation
                    : null,
                child: _isContinuing
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Continue'),
              ),
            ),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Back'),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _continueWithLocation() async {
    if (_isContinuing || !_acceptedTerms) return;

    setState(() => _isContinuing = true);
    await _persistConsent();

    final loc = LocationService();
    final result = await loc.getCurrentPosition();

    if (!mounted) return;

    if (result.hasError && result.canOpenSettings) {
      await showDialog(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Enable Location'),
          content: Text(
            result.error ??
                'TrustBond needs GPS to determine your location for accurate reporting.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Not now'),
            ),
            TextButton(
              onPressed: () async {
                Navigator.of(context).pop();
                if (result.errorType == LocationErrorType.serviceDisabled) {
                  await loc.openLocationSettings();
                } else {
                  await loc.openAppSettings();
                }
              },
              child: const Text('Open Settings'),
            ),
          ],
        ),
      );

      if (!mounted) return;
    }

    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const MainShell()),
    );
  }
}

const String _termsAndConditionsText = '''
TrustBond Terms and Conditions
Effective Date: 29 March 2026

Please read these Terms and Conditions carefully before using TrustBond.
By selecting "Accept" and continuing to use this app, you agree to be bound by these terms.

1. Service purpose
TrustBond is a community safety reporting platform that allows users to submit incident reports, supporting media, and location context to help responsible institutions respond.

2. Eligibility and lawful use
You agree to use the app only for lawful, good-faith safety reporting. You must not submit knowingly false, misleading, abusive, discriminatory, or malicious reports.

3. No account registration
TrustBond is designed for anonymous participation and does not require account creation with personal identity credentials.

4. Anonymous identifier
The app may generate and store an anonymous device identifier to improve service quality, trust scoring, abuse prevention, and report continuity.

5. Location and device permissions
TrustBond requests location and other relevant permissions only to enable reporting features and route incidents accurately. If permissions are denied, some features may not work as intended.

6. Content submitted by you
You remain responsible for the content you submit, including text, images, and other evidence. You confirm that your submission does not intentionally violate the rights of others.

7. Verification and moderation
Reports may be reviewed by automated systems and authorized personnel for verification, prioritization, and abuse prevention before action is taken.

8. Safety and emergency limitation
TrustBond is not a guaranteed emergency response service. In urgent danger, users should immediately contact official emergency channels.

9. Availability and updates
We may modify, suspend, or improve any part of the service at any time, including security controls, functionality, and compatibility requirements.

10. Limitation of liability
To the maximum extent permitted by applicable law, TrustBond and its operators are not liable for indirect, incidental, or consequential damages arising from app use or inability to use the app.

11. Termination of access
Use of the app may be restricted for misuse, policy violations, abuse patterns, or attempts to compromise platform integrity.

12. Changes to these terms
These terms may be revised. Continued use after updates constitutes acceptance of the latest version.

13. Contact and governance
If you have questions regarding these terms, contact the TrustBond administration team through your organization channels.
''';

const String _privacyPolicyText = '''
TrustBond Privacy Policy
Effective Date: 29 March 2026

This Privacy Policy explains how TrustBond collects, uses, stores, and protects information when you use the app.

1. Information we collect
- Anonymous device identifier generated for platform operation and abuse prevention
- Report content you provide (incident type, description, optional media attachments)
- Location data submitted during reporting to determine relevant response area
- Technical metadata required for diagnostics, service security, and reliability

2. Information we generally do not require
- Full legal name
- Personal account password (TrustBond does not require standard account sign-up)
- Personal phone number for core anonymous reporting workflows

3. Why we process information
- Receive and process incident reports
- Evaluate report credibility and priority
- Forward relevant reports to authorized response institutions
- Detect abuse, spam, fraud, and policy violations
- Maintain and improve system reliability, safety, and performance

4. Legal basis and consent
By selecting "Accept" and using TrustBond, you consent to processing described in this policy where consent is required by applicable law.

5. Data sharing
Information may be shared with authorized personnel, public safety partners, and service providers only as necessary to operate the platform, assess incidents, and support legitimate response actions.

6. Data retention
Information is retained only for as long as necessary for safety operations, legal obligations, dispute handling, auditing, and system integrity.

7. Data security
TrustBond uses reasonable technical and organizational safeguards to protect information in transit and at rest. No method of transmission or storage is 100% secure.

8. Your choices
You may stop using the app at any time. You can also manage app permissions in your device settings, but disabling permissions may limit essential features.

9. Children and sensitive use
TrustBond is intended for responsible community safety reporting. Users should avoid submitting unnecessary personal or sensitive data about themselves or others.

10. International and third-party processing
Where needed, trusted service providers may process limited data on behalf of TrustBond under appropriate confidentiality and security controls.

11. Policy updates
This policy may be updated periodically. Continued use of the app after changes indicates acceptance of the updated policy.

12. Contact
Questions about privacy can be directed to the TrustBond administration team through official organizational channels.
''';