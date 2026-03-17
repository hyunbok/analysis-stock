import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/utils/format_utils.dart';

/// 등락률 표시 위젯 — ▲/▼ 화살표 + 색상 자동 적용.
///
/// 양수: buyColor (상승), 음수: sellColor (하락), 0: holdColor (보합).
class ChangeRateText extends StatelessWidget {
  final double rate;
  final TextStyle? style;
  final bool showArrow;

  const ChangeRateText({
    super.key,
    required this.rate,
    this.style,
    this.showArrow = true,
  });

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<TradingColors>()!;
    final Color color;
    final String prefix;

    if (rate > 0) {
      color = colors.buyColor;
      prefix = showArrow ? '▲ ' : '';
    } else if (rate < 0) {
      color = colors.sellColor;
      prefix = showArrow ? '▼ ' : '';
    } else {
      color = colors.holdColor;
      prefix = '';
    }

    return Text(
      '$prefix${FormatUtils.formatRate(rate)}',
      style: (style ?? Theme.of(context).textTheme.bodySmall)?.copyWith(
        color: color,
        fontFamily: 'Inter',
        fontFeatures: const [FontFeature.tabularFigures()],
        fontWeight: FontWeight.w600,
      ),
    );
  }
}
