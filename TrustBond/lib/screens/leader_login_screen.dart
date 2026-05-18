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

class _LeaderLoginScreenState extends State<LeaderLoginScreen> {
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

  @override
  void initState() {
    super.initState();
    _tryAutoLogin();
  }

  @override
  void dispose() {
    _resendTimer?.cancel();
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    _otpCtrl.dispose();
    super.dispose();
  }

  Future<void> _tryAutoLogin() async {
    try {
      final token = await _leader.getToken();
      if (token == null || token.isEmpty) return;
      await _leader.me();
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const LeaderInboxScreen()),
      );
    } catch (_) {
      await _leader.logout();
    }
  }

  void _startResendCountdown(int seconds) {
    _resendTimer?.cancel();
    setState(() => _resendInSeconds = seconds);
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
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
    if (!email.contains('@') || !email.contains('.')) {
      return 'Enter a valid email address.';
    }
    return null;
  }

  Future<void> _openSetupScreen() async {
    final email = _emailCtrl.text.trim();
    final setupDone = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => LeaderSetupPasswordScreen(initialEmail: email),
      ),
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
    if (emailError != null) {
      setState(() => _error = emailError);
      return;
    }
    if (_resendInSeconds > 0) return;

    setState(() {
      _loading = true;
      _error = null;
      _success = null;
    });
    try {
      final retryAfter =
          await _leader.requestLoginCodeWithRetryAfter(email: _emailCtrl.text);
      if (!mounted) return;
      setState(() {
        _codeSent = true;
        _success = 'Check your email for the login code.';
      });
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
    if (emailError != null) {
      setState(() => _error = emailError);
      return;
    }
    if (_passwordCtrl.text.trim().isEmpty) {
      setState(() => _error = 'Enter your password.');
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
      _success = null;
    });
    try {
      await _leader.login(
        email: _emailCtrl.text,
        password: _passwordCtrl.text,
      );
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
    if (emailError != null) {
      setState(() => _error = emailError);
      return;
    }
    if (_otpCtrl.text.trim().isEmpty) {
      setState(() => _error = 'Enter the code from your email.');
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
      _success = null;
    });
    try {
      await _leader.verifyLoginCode(
        email: _emailCtrl.text,
        code: _otpCtrl.text,
      );
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
    final isOtp = _signInMethod == _SignInMethod.otp;
    final primaryLabel = _signInMethod == _SignInMethod.password
        ? 'Sign in'
        : (_codeSent ? 'Verify code' : 'Send login code');

    return Scaffold(
      appBar: AppBar(
        title: const Text('Local Leader'),
        backgroundColor: AppColors.bg,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Sign in to verify incidents in your cell or village.',
                style: TextStyle(color: AppColors.muted, fontSize: 12),
              ),
              const SizedBox(height: 20),
              SegmentedButton<_SignInMethod>(
                segments: const [
                  ButtonSegment(
                    value: _SignInMethod.password,
                    label: Text('Password'),
                    icon: Icon(Icons.lock_outline, size: 18),
                  ),
                  ButtonSegment(
                    value: _SignInMethod.otp,
                    label: Text('Email code'),
                    icon: Icon(Icons.mark_email_read_outlined, size: 18),
                  ),
                ],
                selected: {_signInMethod},
                onSelectionChanged: (selected) {
                  if (selected.isNotEmpty) _switchSignInMethod(selected.first);
                },
              ),
              const SizedBox(height: 20),
              TextField(
                controller: _emailCtrl,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                autofillHints: const [AutofillHints.email],
                decoration: const InputDecoration(
                  labelText: 'Email',
                  hintText: 'Registered leader email',
                ),
              ),
              const SizedBox(height: 12),
              if (!isOtp) ...[
                TextField(
                  controller: _passwordCtrl,
                  obscureText: _obscurePassword,
                  autofillHints: const [AutofillHints.password],
                  onSubmitted: (_) => _loading ? null : _signInWithPassword(),
                  decoration: InputDecoration(
                    labelText: 'Password',
                    suffixIcon: IconButton(
                      icon: Icon(
                        _obscurePassword ? Icons.visibility_off : Icons.visibility,
                      ),
                      onPressed: () =>
                          setState(() => _obscurePassword = !_obscurePassword),
                    ),
                  ),
                ),
              ] else if (_codeSent) ...[
                TextField(
                  controller: _otpCtrl,
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  decoration: const InputDecoration(
                    labelText: 'Login code',
                    hintText: '6-digit code from email',
                  ),
                ),
                if (_resendInSeconds > 0)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      'Resend available in ${_resendInSeconds}s',
                      style: const TextStyle(color: AppColors.muted, fontSize: 11),
                    ),
                  )
                else
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: _loading ? null : _requestOtp,
                      child: const Text('Resend code'),
                    ),
                  ),
              ],
              const SizedBox(height: 12),
              if (_error != null)
                Text(
                  _error!,
                  style: const TextStyle(color: AppColors.danger, fontSize: 12),
                ),
              if (_success != null)
                Text(
                  _success!,
                  style: const TextStyle(color: AppColors.ok, fontSize: 12),
                ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _loading ||
                          (isOtp && !_codeSent && _resendInSeconds > 0)
                      ? null
                      : _onPrimaryAction,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: _loading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : Text(primaryLabel),
                ),
              ),
              const SizedBox(height: 8),
              if (isOtp && !_codeSent)
                Text(
                  'We will email a one-time code to your registered address.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: AppColors.muted.withValues(alpha: 0.9), fontSize: 11),
                ),
              const SizedBox(height: 20),
              const Divider(),
              const SizedBox(height: 8),
              Text(
                'First time here?',
                style: TextStyle(
                  color: AppColors.muted.withValues(alpha: 0.95),
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                'An admin must add your email in the police dashboard. Then create your password using the setup code we email you.',
                style: TextStyle(color: AppColors.muted, fontSize: 11),
              ),
              const SizedBox(height: 10),
              OutlinedButton.icon(
                onPressed: _loading ? null : _openSetupScreen,
                icon: const Icon(Icons.person_add_outlined, size: 18),
                label: const Text('Register / set up password'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
