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
  bool _docsRead = false;

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
      if (accepted) _docsRead = true;
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
            'Review the Terms & Conditions and Privacy Policy before accepting.',
            style: TextStyle(fontSize: 11.5, color: AppColors.muted, height: 1.5),
          ),
          const SizedBox(height: 14),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () async {
                final done = await _showLegalSheetRequireFullRead();
                if (!mounted || !done) return;
                setState(() => _docsRead = true);
              },
              icon: Icon(
                _docsRead ? Icons.check_circle_rounded : Icons.article_outlined,
                size: 16,
                color: _docsRead ? Colors.green : null,
              ),
              label: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Terms & Privacy Policy'),
                  if (_docsRead)
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
                      'Tap to review',
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
                  color: _docsRead
                      ? Colors.green.withValues(alpha: 0.4)
                      : AppColors.border,
                ),
                backgroundColor:
                    _docsRead ? Colors.green.withValues(alpha: 0.04) : null,
                alignment: Alignment.centerLeft,
              ),
            ),
          ),
          const SizedBox(height: 14),
          if (!_docsRead)
            const Padding(
              padding: EdgeInsets.only(bottom: 10),
              child: Row(
                children: [
                  Icon(Icons.info_outline, size: 13, color: AppColors.muted),
                  SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Scroll to the end to enable acceptance.',
                      style: TextStyle(fontSize: 11, color: AppColors.muted, height: 1.5),
                    ),
                  ),
                ],
              ),
            ),
          GestureDetector(
            onTap: _docsRead ? () => setState(() => _acceptedTerms = !_acceptedTerms) : null,
            child: AnimatedOpacity(
              opacity: _docsRead ? 1.0 : 0.45,
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
                        onChanged: _docsRead
                            ? (v) => setState(() => _acceptedTerms = v ?? false)
                            : null,
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

  Future<bool> _showLegalSheetRequireFullRead() async {
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
                      const Text(
                        'Terms & Privacy Policy',
                        style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
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
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  _termsAndConditionsText,
                                  style: const TextStyle(
                                    fontSize: 13,
                                    color: AppColors.muted,
                                    height: 1.8,
                                  ),
                                ),
                                const SizedBox(height: 8),
                                const Divider(),
                                const SizedBox(height: 8),
                                Text(
                                  _privacyPolicyText,
                                  style: const TextStyle(
                                    fontSize: 13,
                                    color: AppColors.muted,
                                    height: 1.8,
                                  ),
                                ),
                              ],
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
Coverage: Musanze District, Northern Province, Rwanda

This Privacy Policy explains what information TrustBond collects, how it is used, and how it is protected.

1. Information we collect

a) Anonymous device identifier
When you first open TrustBond, the app generates a secure anonymous ID on your device. This ID is a mathematical hash that cannot be reversed to identify you. It is used to track your report history, calculate your trust score, and prevent abuse.

b) Incident report content
When you submit a report, TrustBond collects the incident type, your written description, any photos or videos you attach, and the GPS coordinates at the time of submission.

c) Location data (two uses)
- Reporting: your location is attached to the report to route it to the correct local leader in your cell or village within Musanze District.
- Safety alerts: while the app is open and running in the background, TrustBond monitors your GPS location to alert you when you come close to a known security hotspot. This location data is processed locally on your device and is not continuously uploaded to a server.

d) Technical metadata
Standard technical information (device OS version, connection status) may be collected for system reliability and security purposes.

2. Information we do not collect
- Your full name
- Your phone number
- Your email address
- Any government-issued identification

3. How we use your information
- To receive, screen, and process incident reports
- To route verified reports to the assigned local leader in Musanze District
- To send you real-time safety alerts based on your proximity to security hotspots
- To evaluate report credibility through automated AI screening
- To prevent abuse, spam, and false reporting
- To maintain and improve system reliability

4. Who sees your reports
Reports that pass AI screening are forwarded to the local leader assigned to your cell or village. Leaders can see the incident details, attached evidence, and location. They cannot see who submitted the report. No personal identity data is ever attached to a report.

5. Legal basis and consent
By selecting "Accept" and continuing to use TrustBond, you consent to the data processing described in this policy.

6. Data retention
Anonymous device IDs and report data are retained for as long as needed to support safety investigations, maintain trust scoring, and comply with applicable obligations. No personally identifiable data is collected, so there is nothing personally identifiable to delete.

7. Data security
TrustBond uses HTTPS/TLS encryption for all data in transit between the app and server. Stored evidence and report data are accessible only to authorized personnel. No security system is 100% guaranteed, but reasonable safeguards are in place.

8. Your choices
You may stop using the app at any time. You can disable location permissions in your device settings, but this will prevent incident reporting and safety alerts from functioning correctly.

9. Emergency limitation
TrustBond is a community reporting tool, not a guaranteed emergency response service. In immediate danger, contact official emergency services directly.

10. Policy updates
This policy may be revised. Continued use after updates constitutes acceptance of the latest version.

11. Contact
Questions about this policy can be directed to the TrustBond administration team through official organizational channels.
''';