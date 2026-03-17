import 'package:flutter/material.dart';

import '../../../core/constants/app_colors.dart';

enum AiStatus { on, off, analyzing }

/// AI 자동매매 상태 배지.
///
/// - on: 민트색 배경 + "AI 작동중"
/// - off: 회색 배경 + "중지됨"
/// - analyzing: 펄스 애니메이션 + "분석중..."
class AiStatusBadge extends StatefulWidget {
  final AiStatus status;

  const AiStatusBadge({super.key, required this.status});

  @override
  State<AiStatusBadge> createState() => _AiStatusBadgeState();
}

class _AiStatusBadgeState extends State<AiStatusBadge>
    with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;

  static const _aiOnColor = AppColors.aiOn;
  static const _aiOffColor = AppColors.aiOff;
  static const _analyzingColor = AppColors.aiAnalyzing;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      duration: const Duration(milliseconds: 800),
      vsync: this,
    );
    _pulseAnimation = Tween<double>(begin: 0.6, end: 1.0).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
    if (widget.status == AiStatus.analyzing) {
      _pulseController.repeat(reverse: true);
    }
  }

  @override
  void didUpdateWidget(AiStatusBadge oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.status == AiStatus.analyzing) {
      _pulseController.repeat(reverse: true);
    } else {
      _pulseController.stop();
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final (color, label) = switch (widget.status) {
      AiStatus.on => (_aiOnColor, 'AI 작동중'),
      AiStatus.off => (_aiOffColor, '중지됨'),
      AiStatus.analyzing => (_analyzingColor, '분석중...'),
    };

    Widget badge = Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: color,
              fontWeight: FontWeight.w600,
            ),
      ),
    );

    if (widget.status == AiStatus.analyzing) {
      badge = AnimatedBuilder(
        animation: _pulseAnimation,
        builder: (context, child) =>
            Opacity(opacity: _pulseAnimation.value, child: child),
        child: badge,
      );
    }

    return badge;
  }
}
