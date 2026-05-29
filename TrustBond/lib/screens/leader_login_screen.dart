import 'package:flutter/material.dart';
import 'dart:async';

import '../config/theme.dart';
import '../services/leader_service.dart';
import 'leader_inbox_screen.dart';
import 'leader_setup_password_screen.dart';

enum _SignInMethod { password, otp }

class LeaderLoginScreen extends StatefulWidget {
  const LeaderLoginScreen({super.key});

  @override
  State<LeaderLoginScreen> createState() => _LeaderLoginScreenState();
}

class _LeaderLoginScreenState extends State<LeaderLoginScreen>
    with TickerProviderStateMixin {
  final _leader = LeaderService();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  final _otpCtrl = TextEditingController();
  bool _loading = false;
  bool _codeSent = false;
  bool _obscurePassword = true;
  _SignInMethod _signInMethod = _SignInMethod.password;
  int _resendInSeconds = 0;
  Timer? _resendTimer;
  String? _error;
  String? _success;
  bool _sessionChecking = true;

  // Animations
  late final AnimationController _entranceCtrl;
  late final AnimationController _logoCtrl;
  late final Animation<double> _logoScale;
  late final Animation<double> _logoOpacity;
  late final Animation<Offset> _headerSlide;
  late final Animation<double> _formFade;
  late final Animation<Offset> _formSlide;

  @override
  void initState() {
    super.initState();

    _entranceCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    );
    _logoCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1800),
    )..repeat(reverse: true);

    _logoScale = Tween<double>(begin: 0.7, end: 1.0).animate(
      CurvedAnimation(
        parent: _entranceCtrl,
        curve: const Interval(0.0, 0.55, curve: Curves.elasticOut),
      ),
    );
    _logoOpacity = Tween<double>(begin: 0.0, end: 1.0).animate(
      CurvedAnimation(
        parent: _entranceCtrl,
        curve: const Interval(0.0, 0.4, curve: Curves.easeOut),
      ),
    );
    _headerSlide = Tween<Offset>(
      begin: const Offset(0, -0.3),
      end: Offset.zero,
    ).animate(
      CurvedAnimation(
        parent: _entranceCtrl,
        curve: const Interval(0.0, 0.6, curve: Curves.easeOutCubic),
      ),
    );
    _formFade = Tween<double>(begin: 0.0, end: 1.0).animate(
      CurvedAnimation(
        parent: _entranceCtrl,
        curve: const Interval(0.35, 1.0, curve: Curves.easeOut),
      ),
    );
    _formSlide = Tween<Offset>(
      begin: const Offset(0, 0.15),
      end: Offset.zero,
    ).animate(
      CurvedAnimation(
        parent: _entranceCtrl,
        curve: const Interval(0.35, 1.0, curve: Curves.easeOutCubic),
      ),
    );

    _tryAutoLogin();
  }

  @override
  void dispose() {
    _resendTimer?.cancel();
    _entranceCtrl.dispose();
    _logoCtrl.dispose();
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    _otpCtrl.dispose();
    super.dispose();
  }

  Future<void> _tryAutoLogin() async {
    try {
      final active = await _leader.isSessionActive();
      if (!mounted) return;
      if (active) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const LeaderInboxScreen()),
        );
        return;
      }
    } catch (_) {
      await _leader.logout();
    } finally {
      if (mounted) {
        setState(() => _sessionChecking = false);
        _entranceCtrl.forward();
      }
    }
  }

  void _startResendCountdown(int seconds) {
    _resendTimer?.cancel();
    setState(() => _resendInSeconds = seconds);
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) { timer.cancel(); return; }
      if (_resendInSeconds <= 1) {
        timer.cancel();
        setState(() => _resendInSeconds = 0);
      } else {
        setState(() => _resendInSeconds -= 1);
      }
    });
  }

  String? _validateEmail() {
    final email = _emailCtrl.text.trim();
    if (email.isEmpty) return 'Enter your registered email.';
    if (!email.contains('@') || !email.contains('.')) return 'Enter a valid email address.';
    return null;
  }

  Future<void> _openSetupScreen() async {
    final email = _emailCtrl.text.trim();
    final setupDone = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => LeaderSetupPasswordScreen(initialEmail: email)),
    );
    if (!mounted) return;
    if (setupDone == true) {
      setState(() {
        _signInMethod = _SignInMethod.password;
        _error = null;
        _success = 'Password created. Sign in with your email and password below.';
        _codeSent = false;
        _otpCtrl.clear();
      });
    }
  }

  Future<void> _requestOtp() async {
    final emailError = _validateEmail();
    if (emailError != null) { setState(() => _error = emailError); return; }
    if (_resendInSeconds > 0) return;
    setState(() { _loading = true; _error = null; _success = null; });
    try {
      final retryAfter = await _leader.requestLoginCodeWithRetryAfter(email: _emailCtrl.text);
      if (!mounted) return;
      setState(() { _codeSent = true; _success = 'Check your email for the login code.'; });
      _startResendCountdown((retryAfter != null && retryAfter > 0) ? retryAfter : 30);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _signInWithPassword() async {
    final emailError = _validateEmail();
    if (emailError != null) { setState(() => _error = emailError); return; }
    if (_passwordCtrl.text.trim().isEmpty) { setState(() => _error = 'Enter your password.'); return; }
    setState(() { _loading = true; _error = null; _success = null; });
    try {
      await _leader.login(email: _emailCtrl.text, password: _passwordCtrl.text);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const LeaderInboxScreen()),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _verifyOtp() async {
    final emailError = _validateEmail();
    if (emailError != null) { setState(() => _error = emailError); return; }
    if (_otpCtrl.text.trim().isEmpty) { setState(() => _error = 'Enter the code from your email.'); return; }
    setState(() { _loading = true; _error = null; _success = null; });
    try {
      await _leader.verifyLoginCode(email: _emailCtrl.text, code: _otpCtrl.text);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const LeaderInboxScreen()),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _switchSignInMethod(_SignInMethod method) {
    if (_signInMethod == method) return;
    setState(() {
      _signInMethod = method;
      _error = null;
      _success = null;
      if (method == _SignInMethod.password) {
        _codeSent = false;
        _otpCtrl.clear();
        _resendTimer?.cancel();
        _resendInSeconds = 0;
      } else {
        _passwordCtrl.clear();
      }
    });
  }

  Future<void> _onPrimaryAction() async {
    if (_signInMethod == _SignInMethod.password) {
      await _signInWithPassword();
    } else if (_codeSent) {
      await _verifyOtp();
    } else {
      await _requestOtp();
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_sessionChecking) {
      return Scaffold(
        backgroundColor: AppColors.bg,
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: Image.asset('assets/images/logo.jpeg', width: 56, height: 56, fit: BoxFit.cover),
              ),
              const SizedBox(height: 20),
              const SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accent),
              ),
            ],
          ),
        ),
      );
    }

    final isOtp = _signInMethod == _SignInMethod.otp;
    final primaryLabel = _signInMethod == _SignInMethod.password
        ? 'Sign in'
        : (_codeSent ? 'Verify code' : 'Send login code');

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 36),
              // ── Header ────────────────────────────────────────────────
              FadeTransition(
                opacity: _logoOpacity,
                child: SlideTransition(
                  position: _headerSlide,
                  child: Column(
                    children: [
                      AnimatedBuilder(
                        animation: _logoCtrl,
                        builder: (_, child) {
                          final glow = _logoCtrl.value * 0.15 + 0.08;
                          return ScaleTransition(
                            scale: _logoScale,
                            child: Container(
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                boxShadow: [
                                  BoxShadow(
                                    color: AppColors.accent.withValues(alpha: glow),
                                    blurRadius: 28,
                                    spreadRadius: 6,
                                  ),
                                ],
                              ),
                              child: child,
                            ),
                          );
                        },
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(22),
                          child: Image.asset(
                            'assets/images/logo.jpeg',
                            width: 76,
                            height: 76,
                            fit: BoxFit.cover,
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'Local Leader',
                        style: TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.w800,
                          color: AppColors.text,
                          letterSpacing: -0.3,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'Sign in to verify incidents in your cell or village.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: AppColors.muted, fontSize: 12.5, height: 1.5),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 32),

              // ── Form card ─────────────────────────────────────────────
              FadeTransition(
                opacity: _formFade,
                child: SlideTransition(
                  position: _formSlide,
                  child: Container(
                    decoration: BoxDecoration(
                      color: AppColors.surface,
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: AppColors.border),
                    ),
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        // Method toggle
                        Container(
                          decoration: BoxDecoration(
                            color: AppColors.surface2,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          padding: const EdgeInsets.all(4),
                          child: Row(
                            children: [
                              _methodTab(
                                label: 'Password',
                                icon: Icons.lock_outline_rounded,
                                selected: _signInMethod == _SignInMethod.password,
                                onTap: () => _switchSignInMethod(_SignInMethod.password),
                              ),
                              _methodTab(
                                label: 'Email code',
                                icon: Icons.mark_email_read_outlined,
                                selected: _signInMethod == _SignInMethod.otp,
                                onTap: () => _switchSignInMethod(_SignInMethod.otp),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 20),

                        // Email field
                        TextField(
                          controller: _emailCtrl,
                          keyboardType: TextInputType.emailAddress,
                          autocorrect: false,
                          autofillHints: const [AutofillHints.email],
                          decoration: const InputDecoration(
                            labelText: 'Email',
                            hintText: 'Registered leader email',
                            prefixIcon: Icon(Icons.email_outlined, size: 18),
                          ),
                        ),
                        const SizedBox(height: 12),

                        // Password / OTP fields
                        AnimatedSwitcher(
                          duration: const Duration(milliseconds: 280),
                          transitionBuilder: (child, anim) => FadeTransition(
                            opacity: anim,
                            child: SlideTransition(
                              position: Tween<Offset>(
                                begin: const Offset(0, 0.08),
                                end: Offset.zero,
                              ).animate(anim),
                              child: child,
                            ),
                          ),
                          child: _buildCredentialFields(isOtp),
                        ),

                        const SizedBox(height: 12),

                        // Feedback messages
                        AnimatedSwitcher(
                          duration: const Duration(milliseconds: 250),
                          child: _buildFeedback(),
                        ),
                        const SizedBox(height: 16),

                        // Primary action button
                        AnimatedContainer(
                          duration: const Duration(milliseconds: 200),
                          height: 50,
                          child: ElevatedButton(
                            onPressed: _loading || (isOtp && !_codeSent && _resendInSeconds > 0)
                                ? null
                                : _onPrimaryAction,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppColors.accent,
                              foregroundColor: const Color(0xFF0F172A),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                              elevation: 0,
                            ),
                            child: AnimatedSwitcher(
                              duration: const Duration(milliseconds: 200),
                              child: _loading
                                  ? const SizedBox(
                                      key: ValueKey('loader'),
                                      width: 20,
                                      height: 20,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2.5,
                                        color: Color(0xFF0F172A),
                                      ),
                                    )
                                  : Text(
                                      primaryLabel,
                                      key: ValueKey(primaryLabel),
                                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
                                    ),
                            ),
                          ),
                        ),

                        if (isOtp && !_codeSent) ...[
                          const SizedBox(height: 10),
                          const Text(
                            'We will email a one-time code to your registered address.',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: AppColors.muted, fontSize: 11),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),

              // ── Register section ──────────────────────────────────────
              FadeTransition(
                opacity: _formFade,
                child: Container(
                  decoration: BoxDecoration(
                    color: AppColors.surface,
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: AppColors.border),
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
                  child: Row(
                    children: [
                      Container(
                        width: 38,
                        height: 38,
                        decoration: BoxDecoration(
                          color: AppColors.accent.withValues(alpha: 0.10),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: const Icon(Icons.person_add_alt_1_rounded, size: 18, color: AppColors.accent),
                      ),
                      const SizedBox(width: 12),
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('First time here?',
                                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.text)),
                            SizedBox(height: 2),
                            Text('Set up your password with the code sent by admin.',
                                style: TextStyle(fontSize: 11, color: AppColors.muted, height: 1.4)),
                          ],
                        ),
                      ),
                      const SizedBox(width: 8),
                      OutlinedButton(
                        onPressed: _loading ? null : _openSetupScreen,
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                          side: const BorderSide(color: AppColors.border),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        ),
                        child: const Text('Set up', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 32),
            ],
          ),
        ),
      ),
    );
  }

  Widget _methodTab({
    required String label,
    required IconData icon,
    required bool selected,
    required VoidCallback onTap,
  }) {
    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeInOut,
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: selected ? AppColors.accent.withValues(alpha: 0.15) : Colors.transparent,
            borderRadius: BorderRadius.circular(9),
            border: selected
                ? Border.all(color: AppColors.accent.withValues(alpha: 0.35))
                : Border.all(color: Colors.transparent),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 15, color: selected ? AppColors.accent : AppColors.muted),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                  color: selected ? AppColors.accent : AppColors.muted,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCredentialFields(bool isOtp) {
    if (!isOtp) {
      return Column(
        key: const ValueKey('password-fields'),
        children: [
          TextField(
            controller: _passwordCtrl,
            obscureText: _obscurePassword,
            autofillHints: const [AutofillHints.password],
            onSubmitted: (_) => _loading ? null : _signInWithPassword(),
            decoration: InputDecoration(
              labelText: 'Password',
              prefixIcon: const Icon(Icons.lock_outline_rounded, size: 18),
              suffixIcon: IconButton(
                icon: Icon(
                  _obscurePassword ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                  size: 18,
                ),
                onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
              ),
            ),
          ),
        ],
      );
    }

    if (!_codeSent) {
      return const SizedBox(key: ValueKey('otp-empty'), height: 0);
    }

    return Column(
      key: const ValueKey('otp-fields'),
      children: [
        TextField(
          controller: _otpCtrl,
          keyboardType: TextInputType.number,
          maxLength: 6,
          decoration: const InputDecoration(
            labelText: 'Login code',
            hintText: '6-digit code from email',
            prefixIcon: Icon(Icons.pin_outlined, size: 18),
          ),
        ),
        if (_resendInSeconds > 0)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Row(
              children: [
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 1.5, color: AppColors.muted),
                ),
                const SizedBox(width: 8),
                Text(
                  'Resend available in ${_resendInSeconds}s',
                  style: const TextStyle(color: AppColors.muted, fontSize: 11),
                ),
              ],
            ),
          )
        else
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: _loading ? null : _requestOtp,
              icon: const Icon(Icons.refresh_rounded, size: 14),
              label: const Text('Resend code', style: TextStyle(fontSize: 12)),
              style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildFeedback() {
    if (_error != null) {
      return Container(
        key: const ValueKey('error'),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: AppColors.danger.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppColors.danger.withValues(alpha: 0.25)),
        ),
        child: Row(
          children: [
            const Icon(Icons.error_outline_rounded, color: AppColors.danger, size: 16),
            const SizedBox(width: 8),
            Expanded(
              child: Text(_error!, style: const TextStyle(color: AppColors.danger, fontSize: 12)),
            ),
          ],
        ),
      );
    }
    if (_success != null) {
      return Container(
        key: const ValueKey('success'),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: AppColors.ok.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppColors.ok.withValues(alpha: 0.25)),
        ),
        child: Row(
          children: [
            const Icon(Icons.check_circle_outline_rounded, color: AppColors.ok, size: 16),
            const SizedBox(width: 8),
            Expanded(
              child: Text(_success!, style: const TextStyle(color: AppColors.ok, fontSize: 12)),
            ),
          ],
        ),
      );
    }
    return const SizedBox(key: ValueKey('none'), height: 0);
  }
}
