import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../services/leader_service.dart';

class LeaderSetupPasswordScreen extends StatefulWidget {
  const LeaderSetupPasswordScreen({super.key});

  @override
  State<LeaderSetupPasswordScreen> createState() => _LeaderSetupPasswordScreenState();
}

class _LeaderSetupPasswordScreenState extends State<LeaderSetupPasswordScreen> {
  final _leader = LeaderService();
  final _emailCtrl = TextEditingController();
  final _codeCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _confirmCtrl = TextEditingController();
  bool _loadingCode = false;
  bool _loadingSubmit = false;
  String? _error;
  String? _success;

  @override
  void dispose() {
    _emailCtrl.dispose();
    _codeCtrl.dispose();
    _passCtrl.dispose();
    _confirmCtrl.dispose();
    super.dispose();
  }

  Future<void> _requestCode() async {
    setState(() {
      _loadingCode = true;
      _error = null;
      _success = null;
    });
    try {
      await _leader.requestSetupCode(email: _emailCtrl.text);
      if (!mounted) return;
      setState(() {
        _success = 'Setup code sent to your email. Check your inbox.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loadingCode = false);
    }
  }

  Future<void> _submit() async {
    if (_passCtrl.text.trim().length < 6) {
      setState(() => _error = 'Password must be at least 6 characters.');
      return;
    }
    if (_passCtrl.text != _confirmCtrl.text) {
      setState(() => _error = 'Password confirmation does not match.');
      return;
    }
    setState(() {
      _loadingSubmit = true;
      _error = null;
      _success = null;
    });
    try {
      await _leader.setPassword(
        email: _emailCtrl.text,
        code: _codeCtrl.text,
        newPassword: _passCtrl.text,
      );
      if (!mounted) return;
      setState(() {
        _success = 'Password set successfully. You can now sign in.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loadingSubmit = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Set Leader Password'),
        backgroundColor: AppColors.bg,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Use your registered email and setup code to create a private password.',
                style: TextStyle(color: AppColors.muted, fontSize: 12),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _emailCtrl,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: 'Email',
                  hintText: 'same as in police dashboard',
                ),
              ),
              const SizedBox(height: 10),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton(
                  onPressed: _loadingCode ? null : _requestCode,
                  child: _loadingCode
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Request Setup Code'),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _codeCtrl,
                decoration: const InputDecoration(labelText: 'Setup code'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _passCtrl,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'New password'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _confirmCtrl,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Confirm password'),
              ),
              const SizedBox(height: 12),
              if (_error != null)
                Text(_error!, style: const TextStyle(color: AppColors.danger, fontSize: 12)),
              if (_success != null)
                Text(_success!, style: const TextStyle(color: AppColors.ok, fontSize: 12)),
              const Spacer(),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _loadingSubmit ? null : _submit,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  child: _loadingSubmit
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Set Password'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

