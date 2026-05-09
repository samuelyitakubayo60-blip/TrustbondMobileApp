import 'package:flutter/material.dart';
import 'dart:async';

import '../config/theme.dart';
import '../services/leader_service.dart';
import 'leader_inbox_screen.dart';
import 'leader_setup_password_screen.dart';

class LeaderLoginScreen extends StatefulWidget {
  const LeaderLoginScreen({super.key});

  @override
  State<LeaderLoginScreen> createState() => _LeaderLoginScreenState();
}

class _LeaderLoginScreenState extends State<LeaderLoginScreen> {
  final _leader = LeaderService();
  final _emailCtrl = TextEditingController();
  final _otpCtrl = TextEditingController();
  bool _loading = false;
  bool _codeSent = false;
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
    _otpCtrl.dispose();
    super.dispose();
  }

  Future<void> _tryAutoLogin() async {
    try {
      final token = await _leader.getToken();
      if (token == null || token.isEmpty) return;
      await _leader.me(); // validates token against backend
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const LeaderInboxScreen()),
      );
    } catch (_) {
      // Invalid/expired token -> keep user on login screen.
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

  Future<void> _requestCode() async {
    if (_resendInSeconds > 0) return;
    setState(() {
      _loading = true;
      _error = null;
      _success = null;
    });
    try {
      final retryAfter = await _leader.requestLoginCodeWithRetryAfter(email: _emailCtrl.text);
      if (!mounted) return;
      setState(() {
        _codeSent = true;
        _success = 'Check your email for the OTP. Enter the code to continue.';
      });
      _startResendCountdown((retryAfter != null && retryAfter > 0) ? retryAfter : 30);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _verifyCode() async {
    setState(() {
      _loading = true;
      _error = null;
      _success = null;
    });
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Local Leader Login'),
        backgroundColor: AppColors.bg,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Sign in to verify incidents in your cell/village.',
                style: TextStyle(color: AppColors.muted, fontSize: 12),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _emailCtrl,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: 'Email',
                  hintText: 'your registered email',
                ),
              ),
              const SizedBox(height: 12),
              if (_codeSent)
                TextField(
                  controller: _otpCtrl,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'OTP code',
                  ),
                ),
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
              if (_codeSent)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          _resendInSeconds > 0
                              ? 'Resend available in ${_resendInSeconds}s'
                              : 'You can request OTP again.',
                          style: const TextStyle(color: AppColors.muted, fontSize: 11),
                        ),
                      ),
                      TextButton(
                        onPressed: (_loading || _resendInSeconds > 0) ? null : _requestCode,
                        child: const Text('Resend OTP'),
                      ),
                    ],
                  ),
                ),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: _loading
                      ? null
                      : () {
                          Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => const LeaderSetupPasswordScreen(),
                            ),
                          );
                        },
                  child: const Text('Set up password with code'),
                ),
              ),
              const Spacer(),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _loading
                      ? null
                      : (_codeSent
                          ? _verifyCode
                          : (_resendInSeconds > 0 ? null : _requestCode)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  child: _loading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : Text(_codeSent ? 'Verify OTP' : 'Send OTP'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

