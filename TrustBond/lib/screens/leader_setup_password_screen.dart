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

class _LeaderSetupPasswordScreenState extends State<LeaderSetupPasswordScreen>
    with SingleTickerProviderStateMixin {
  final _leader = LeaderService();
  late final TextEditingController _emailCtrl;
  final _codeCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _confirmCtrl = TextEditingController();
  bool _loadingCode = false;
  bool _loadingSubmit = false;
  bool _obscurePass = true;
  bool _obscureConfirm = true;
  bool _codeSent = false;
  String? _error;
  String? _success;

  late final AnimationController _entranceCtrl;
  late final Animation<double> _fadeAnim;
  late final Animation<Offset> _slideAnim;

  @override
  void initState() {
    super.initState();
    _emailCtrl = TextEditingController(text: widget.initialEmail.trim());
    _passCtrl.addListener(() => setState(() {}));

    _entranceCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    )..forward();

    _fadeAnim = CurvedAnimation(parent: _entranceCtrl, curve: Curves.easeOut);
    _slideAnim = Tween<Offset>(
      begin: const Offset(0, 0.12),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _entranceCtrl, curve: Curves.easeOutCubic));
  }

  @override
  void dispose() {
    _entranceCtrl.dispose();
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

  // 0–4 strength score
  int _passwordStrength(String p) {
    if (p.isEmpty) return 0;
    int score = 0;
    if (p.length >= 8) score++;
    if (p.contains(RegExp(r'[A-Z]'))) score++;
    if (p.contains(RegExp(r'[0-9]'))) score++;
    if (p.contains(RegExp(r'[!@#\$%^&*(),.?":{}|<>]'))) score++;
    return score;
  }

  Future<void> _requestCode() async {
    final emailError = _validateEmail();
    if (emailError != null) { setState(() => _error = emailError); return; }
    setState(() { _loadingCode = true; _error = null; _success = null; });
    try {
      await _leader.requestSetupCode(email: _emailCtrl.text);
      if (!mounted) return;
      setState(() {
        _codeSent = true;
        _success = 'Setup code sent — check your inbox (and spam folder).';
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
    if (emailError != null) { setState(() => _error = emailError); return; }
    if (_codeCtrl.text.trim().isEmpty) {
      setState(() => _error = 'Enter the setup code from your email.');
      return;
    }
    if (_passCtrl.text.trim().length < 6) {
      setState(() => _error = 'Password must be at least 6 characters.');
      return;
    }
    if (_passCtrl.text != _confirmCtrl.text) {
      setState(() => _error = 'Passwords do not match.');
      return;
    }

    setState(() { _loadingSubmit = true; _error = null; _success = null; });
    try {
      await _leader.setPassword(
        email: _emailCtrl.text,
        code: _codeCtrl.text,
        newPassword: _passCtrl.text,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Row(
            children: [
              Icon(Icons.check_circle_outline_rounded, color: Colors.white, size: 18),
              SizedBox(width: 10),
              Text('Password set. You can now sign in.'),
            ],
          ),
          backgroundColor: AppColors.ok,
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
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
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        title: const Text('Set up password'),
        backgroundColor: AppColors.bg,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 18),
          onPressed: () => Navigator.of(context).pop(false),
        ),
      ),
      body: SafeArea(
        child: FadeTransition(
          opacity: _fadeAnim,
          child: SlideTransition(
            position: _slideAnim,
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 8, 24, 32),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // ── Intro banner ───────────────────────────────────────
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: AppColors.accent.withValues(alpha: 0.07),
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: AppColors.accent.withValues(alpha: 0.2)),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 40,
                          height: 40,
                          decoration: BoxDecoration(
                            color: AppColors.accent.withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: const Icon(Icons.shield_outlined, size: 20, color: AppColors.accent),
                        ),
                        const SizedBox(width: 12),
                        const Expanded(
                          child: Text(
                            'Your admin has registered you. '
                            'Request a setup code, then choose your password below.',
                            style: TextStyle(color: AppColors.muted, fontSize: 12, height: 1.55),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),

                  // ── Step 1 ────────────────────────────────────────────
                  _buildStepCard(
                    step: 1,
                    title: 'Request setup code',
                    subtitle: 'Enter your registered email and send the code.',
                    done: _codeSent,
                    child: Column(
                      children: [
                        TextField(
                          controller: _emailCtrl,
                          keyboardType: TextInputType.emailAddress,
                          autocorrect: false,
                          autofillHints: const [AutofillHints.email],
                          decoration: const InputDecoration(
                            labelText: 'Email',
                            hintText: 'Same email as in the admin dashboard',
                            prefixIcon: Icon(Icons.email_outlined, size: 18),
                          ),
                        ),
                        const SizedBox(height: 12),
                        SizedBox(
                          width: double.infinity,
                          height: 46,
                          child: OutlinedButton.icon(
                            onPressed: _loadingCode ? null : _requestCode,
                            icon: _loadingCode
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accent),
                                  )
                                : Icon(
                                    _codeSent ? Icons.check_circle_outline_rounded : Icons.mail_outline_rounded,
                                    size: 17,
                                    color: _codeSent ? AppColors.ok : AppColors.accent,
                                  ),
                            label: Text(
                              _codeSent ? 'Code sent — resend?' : 'Send setup code',
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                                color: _codeSent ? AppColors.ok : AppColors.accent,
                              ),
                            ),
                            style: OutlinedButton.styleFrom(
                              side: BorderSide(
                                color: _codeSent
                                    ? AppColors.ok.withValues(alpha: 0.4)
                                    : AppColors.accent.withValues(alpha: 0.4),
                              ),
                              backgroundColor: _codeSent
                                  ? AppColors.ok.withValues(alpha: 0.04)
                                  : AppColors.accent.withValues(alpha: 0.04),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  // ── Step 2 ────────────────────────────────────────────
                  _buildStepCard(
                    step: 2,
                    title: 'Set your password',
                    subtitle: 'Enter the 6-digit code and choose a secure password.',
                    done: false,
                    child: Column(
                      children: [
                        TextField(
                          controller: _codeCtrl,
                          keyboardType: TextInputType.number,
                          maxLength: 6,
                          decoration: const InputDecoration(
                            labelText: 'Setup code',
                            hintText: '6-digit code from email',
                            prefixIcon: Icon(Icons.pin_outlined, size: 18),
                            counterText: '',
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _passCtrl,
                          obscureText: _obscurePass,
                          decoration: InputDecoration(
                            labelText: 'New password',
                            prefixIcon: const Icon(Icons.lock_outline_rounded, size: 18),
                            suffixIcon: IconButton(
                              icon: Icon(
                                _obscurePass ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                                size: 18,
                              ),
                              onPressed: () => setState(() => _obscurePass = !_obscurePass),
                            ),
                          ),
                        ),
                        // Password strength bar
                        if (_passCtrl.text.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          _buildPasswordStrength(_passCtrl.text),
                        ],
                        const SizedBox(height: 12),
                        TextField(
                          controller: _confirmCtrl,
                          obscureText: _obscureConfirm,
                          onSubmitted: (_) => _loadingSubmit ? null : _submit(),
                          decoration: InputDecoration(
                            labelText: 'Confirm password',
                            prefixIcon: const Icon(Icons.lock_outline_rounded, size: 18),
                            suffixIcon: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                if (_confirmCtrl.text.isNotEmpty)
                                  Icon(
                                    _confirmCtrl.text == _passCtrl.text
                                        ? Icons.check_circle_outline_rounded
                                        : Icons.cancel_outlined,
                                    size: 18,
                                    color: _confirmCtrl.text == _passCtrl.text
                                        ? AppColors.ok
                                        : AppColors.danger,
                                  ),
                                IconButton(
                                  icon: Icon(
                                    _obscureConfirm ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                                    size: 18,
                                  ),
                                  onPressed: () => setState(() => _obscureConfirm = !_obscureConfirm),
                                ),
                              ],
                            ),
                          ),
                          onChanged: (_) => setState(() {}),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Feedback
                  AnimatedSwitcher(
                    duration: const Duration(milliseconds: 250),
                    child: _buildFeedback(),
                  ),
                  const SizedBox(height: 20),

                  // Submit button
                  SizedBox(
                    height: 50,
                    child: ElevatedButton(
                      onPressed: _loadingSubmit ? null : _submit,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.accent,
                        foregroundColor: const Color(0xFF0F172A),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        elevation: 0,
                      ),
                      child: AnimatedSwitcher(
                        duration: const Duration(milliseconds: 200),
                        child: _loadingSubmit
                            ? const SizedBox(
                                key: ValueKey('loader'),
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(strokeWidth: 2.5, color: Color(0xFF0F172A)),
                              )
                            : const Text(
                                key: ValueKey('label'),
                                'Create password',
                                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
                              ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildStepCard({
    required int step,
    required String title,
    required String subtitle,
    required bool done,
    required Widget child,
  }) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: done
              ? AppColors.ok.withValues(alpha: 0.35)
              : AppColors.border,
        ),
      ),
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: done
                      ? AppColors.ok.withValues(alpha: 0.15)
                      : AppColors.accent.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Center(
                  child: done
                      ? const Icon(Icons.check_rounded, size: 17, color: AppColors.ok)
                      : Text(
                          '$step',
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w800,
                            color: AppColors.accent,
                          ),
                        ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.text),
                    ),
                    Text(
                      subtitle,
                      style: const TextStyle(fontSize: 11, color: AppColors.muted, height: 1.4),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }

  Widget _buildPasswordStrength(String password) {
    final score = _passwordStrength(password);
    final labels = ['Too short', 'Weak', 'Fair', 'Good', 'Strong'];
    final colors = [
      AppColors.danger,
      AppColors.danger,
      AppColors.warn,
      AppColors.accent,
      AppColors.ok,
    ];
    final label = labels[score.clamp(0, 4)];
    final color = colors[score.clamp(0, 4)];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: List.generate(4, (i) {
            return Expanded(
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                height: 4,
                margin: EdgeInsets.only(right: i < 3 ? 4 : 0),
                decoration: BoxDecoration(
                  color: i < score ? color : AppColors.surface3,
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            );
          }),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.w600),
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
            Expanded(child: Text(_error!, style: const TextStyle(color: AppColors.danger, fontSize: 12))),
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
            Expanded(child: Text(_success!, style: const TextStyle(color: AppColors.ok, fontSize: 12))),
          ],
        ),
      );
    }
    return const SizedBox(key: ValueKey('none'), height: 0);
  }
}
