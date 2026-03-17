import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/utils/format_utils.dart';

/// 실시간 가격 표시 위젯 — 변동 시 배경색 플래시 300ms.
///
/// Inter tabular figures 적용, 천 단위 콤마 포맷.
class PriceText extends StatefulWidget {
  final double price;
  final double? previousPrice;
  final TextStyle? style;
  final String currencySuffix;

  const PriceText({
    super.key,
    required this.price,
    this.previousPrice,
    this.style,
    this.currencySuffix = '',
  });

  @override
  State<PriceText> createState() => _PriceTextState();
}

class _PriceTextState extends State<PriceText>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<Color?> _colorAnimation;
  Color? _flashColor;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(milliseconds: 300),
      vsync: this,
    );
  }

  @override
  void didUpdateWidget(PriceText oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.price != widget.price && widget.previousPrice != null) {
      final colors = Theme.of(context).extension<TradingColors>()!;
      if (widget.price > widget.previousPrice!) {
        _flashColor = colors.buyColor.withOpacity(0.2);
      } else if (widget.price < widget.previousPrice!) {
        _flashColor = colors.sellColor.withOpacity(0.2);
      }
      if (_flashColor != null) {
        _colorAnimation = ColorTween(
          begin: _flashColor,
          end: Colors.transparent,
        ).animate(_controller);
        _controller.forward(from: 0);
      }
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final priceStr = FormatUtils.formatKrw(widget.price);
    final displayText =
        widget.currencySuffix.isEmpty ? priceStr : '$priceStr ${widget.currencySuffix}';

    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return Container(
          color: _controller.isAnimating ? _colorAnimation.value : null,
          child: child,
        );
      },
      child: Text(
        displayText,
        style: (widget.style ?? Theme.of(context).textTheme.bodyMedium)
            ?.copyWith(
          fontFamily: 'Inter',
          fontFeatures: const [FontFeature.tabularFigures()],
        ),
        textAlign: TextAlign.right,
      ),
    );
  }
}
