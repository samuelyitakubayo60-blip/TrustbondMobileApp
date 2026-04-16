import 'package:flutter/material.dart';

import '../config/theme.dart';

class ReportSuccessScreen extends StatefulWidget {
  final String reportId;
  final String incidentTypeName;
  final bool queuedOffline;
  final String? queuedMessage;

  const ReportSuccessScreen({
    super.key,
    required this.reportId,
    required this.incidentTypeName,
    this.queuedOffline = false,
    this.queuedMessage,
  });

  @override
  State<ReportSuccessScreen> createState() => _ReportSuccessScreenState();
}

class _ReportSuccessScreenState extends State<ReportSuccessScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double> _scale;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _scale = CurvedAnimation(parent: _ctrl, curve: Curves.elasticOut);
    _ctrl.forward();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final title =
        widget.queuedOffline ? 'Report Saved' : 'Report Submitted';
    final subtitle = widget.queuedOffline
        ? (widget.queuedMessage ??
            "Saved. Will send automatically when you're back online.")
        : 'Your ${widget.incidentTypeName} report has been received by the server.';

    return Scaffold(
      body: SafeArea(
        child: CustomScrollView(
          slivers: [
            SliverFillRemaining(
              hasScrollBody: false,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 28),
                child: Column(
                  children: [
                    const Spacer(flex: 2),
                    ScaleTransition(
                      scale: _scale,
                      child: Container(
                        width: 90,
                        height: 90,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: LinearGradient(
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                            colors: [AppColors.accent, AppColors.accent2],
                          ),
                        ),
                        child: const Icon(
                          Icons.check_rounded,
                          size: 48,
                          color: AppColors.bg,
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),
                    Text(
                      title,
                      style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      subtitle,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 13,
                        color: AppColors.muted,
                        height: 1.5,
                      ),
                    ),
                    const SizedBox(height: 24),
                    _buildIdCard(),
                    const SizedBox(height: 24),
                    _buildTimeline(),
                    const Spacer(flex: 3),
                    _buildButtons(),
                    const SizedBox(height: 24),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildIdCard() {
    final shortLength = widget.reportId.length < 8 ? widget.reportId.length : 8;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            'Report ID',
            style: TextStyle(fontSize: 11, color: AppColors.muted),
          ),
          const SizedBox(height: 6),
          Text(
            '#${widget.reportId.substring(0, shortLength)}',
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              fontFamily: 'monospace',
              color: AppColors.accent,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTimeline() {
    final steps = widget.queuedOffline
        ? [
            _TimelineStep('Saved on Device', 'Just now', true, true),
            _TimelineStep('Waiting for Signal', 'Pending', false, false),
            _TimelineStep('AI Verification', 'Pending', false, false),
            _TimelineStep('Police Review', 'Waiting', false, false),
          ]
        : [
            _TimelineStep('Submitted', 'Just now', true, true),
            _TimelineStep('Server Validation', 'Processing', true, false),
            _TimelineStep('AI Verification', 'Pending', false, false),
            _TimelineStep('Police Review', 'Waiting', false, false),
          ];

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.card,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Processing Timeline',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 14),
          ...List.generate(steps.length, (i) {
            final s = steps[i];
            final isLast = i == steps.length - 1;
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Column(
                  children: [
                    Container(
                      width: 20,
                      height: 20,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: s.done ? AppColors.accent : AppColors.surface3,
                        border: Border.all(
                          color: s.active
                              ? AppColors.accent
                              : s.done
                                  ? AppColors.accent
                                  : AppColors.border,
                          width: 2,
                        ),
                      ),
                      child: s.done
                          ? const Icon(Icons.check, size: 12, color: AppColors.bg)
                          : null,
                    ),
                    if (!isLast)
                      Container(
                        width: 2,
                        height: 28,
                        color: s.done
                            ? AppColors.accent.withValues(alpha: 0.4)
                            : AppColors.border,
                      ),
                  ],
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          s.label,
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: s.done || s.active ? AppColors.text : AppColors.muted,
                          ),
                        ),
                        Text(
                          s.sub,
                          style: TextStyle(
                            fontSize: 11,
                            color: s.active ? AppColors.accent : AppColors.muted,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            );
          }),
        ],
      ),
    );
  }

  Widget _buildButtons() {
    return Column(
      children: [
        SizedBox(
          width: double.infinity,
          height: 48,
          child: ElevatedButton(
            onPressed: () => Navigator.of(context).popUntil((route) => route.isFirst),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.accent,
              foregroundColor: AppColors.bg,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
            ),
            child: const Text(
              'Return Home',
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
        ),
        const SizedBox(height: 10),
        TextButton(
          onPressed: () => Navigator.of(context).popUntil((route) => route.isFirst),
          child: const Text('Back to Home'),
        ),
      ],
    );
  }
}

class _TimelineStep {
  final String label;
  final String sub;
  final bool done;
  final bool active;

  _TimelineStep(this.label, this.sub, this.done, this.active);
}
