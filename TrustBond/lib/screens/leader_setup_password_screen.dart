import 'package:flutter/material.dart';

import '../config/theme.dart';
import '../services/leader_service.dart';

/// First-time password setup for leaders registered by an admin.
class LeaderSetupPasswordScreen extends StatefulWidget {
  const LeaderSetupPasswordScreen({super.key, this.initialEmail = ''});

  final String initialEmail;

  @override
  State<LeaderSetupPasswordScreen> createState() =>
      _LeaderSetupPasswordScreenState();
}

class _LeaderSetupPasswordScreenState extends State<LeaderSetupPasswordScreen> {
  final _leader = LeaderService();
  late final TextEditingController _emailCtrl;
  final _codeCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _confirmCtrl = TextEditingController();
  bool _loadingCode = false;
  bool _loadingSubmit = false;
  bool _obscurePass = true;
  bool _obscureConfirm = true;
  String? _error;
  String? _success;

  @override
  void initState() {
    super.initState();
    _emailCtrl = TextEditingController(text: widget.initialEmail.trim());
  }

  @override
  void dispose() {
    _emailCtrl.dispose();
    _codeCtrl.dispose();
    _passCtrl.dispose();
    _confirmCtrl.dispose();
    super.dispose();
  }

  String? _validateEmail() {
    final email = _emailCtrl.text.trim();
    if (email.isEmpty) return 'Enter your registered email.';
    if (!email.contains('@') || !email.contains('.')) {
      return 'Enter a valid email address.';
    }
    return null;
  }

  Future<void> _requestCode() async {
    final emailError = _validateEmail();
    if (emailError != null) {
      setState(() => _error = emailError);
      return;
    }

    setState(() {
      _loadingCode = true;
      _error = null;
      _success = null;
    });
    try {
      await _leader.requestSetupCode(email: _emailCtrl.text);
      if (!mounted) return;
      setState(() {
        _success = 'Setup code sent. Check your email (and spam folder).';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loadingCode = false);
    }
  }

  Future<void> _submit() async {
    final emailError = _validateEmail();
    if (emailError != null) {
      setState(() => _error = emailError);
      return;
    }
    if (_codeCtrl.text.trim().isEmpty) {
      setState(() => _error = 'Enter the setup code from your email.');
      return;
    }
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
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Password set. You can now sign in.'),
          backgroundColor: AppColors.ok,
        ),
      );
      Navigator.of(context).pop(true);
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
        title: const Text('Leader registration'),
        backgroundColor: AppColors.bg,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'If your admin registered you, you may have received an email that your account is ready.\n'
                'Step 1: Request a setup code to your registered email.\n'
                'Step 2: Enter the code and choose your password.',
                style: TextStyle(color: AppColors.muted, fontSize: 12),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _emailCtrl,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                autofillHints: const [AutofillHints.email],
                decoration: const InputDecoration(
                  labelText: 'Email',
                  hintText: 'Same email as in police dashboard',
                ),
              ),
              const SizedBox(height: 10),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _loadingCode ? null : _requestCode,
                  icon: _loadingCode
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.mail_outline, size: 18),
                  label: const Text('1. Send setup code to email'),
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _codeCtrl,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: const InputDecoration(
                  labelText: 'Setup code',
                  hintText: '6-digit code',
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _passCtrl,
                obscureText: _obscurePass,
                decoration: InputDecoration(
                  labelText: 'New password',
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscurePass ? Icons.visibility_off : Icons.visibility,
                    ),
                    onPressed: () => setState(() => _obscurePass = !_obscurePass),
                  ),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _confirmCtrl,
                obscureText: _obscureConfirm,
                onSubmitted: (_) => _loadingSubmit ? null : _submit(),
                decoration: InputDecoration(
                  labelText: 'Confirm password',
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscureConfirm ? Icons.visibility_off : Icons.visibility,
                    ),
                    onPressed: () =>
                        setState(() => _obscureConfirm = !_obscureConfirm),
                  ),
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
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _loadingSubmit ? null : _submit,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: _loadingSubmit
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Text('2. Save password'),
                ),
              ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: _loadingSubmit
                    ? null
                    : () => Navigator.of(context).pop(false),
                child: const Text('Back to sign in'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
