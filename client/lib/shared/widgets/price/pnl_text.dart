import 'package:flutter/material.dart';

import '../../../core/utils/format_utils.dart';

/// 손익 텍스트 위젯 — 양수=수익(초록), 음수=손실(빨강), 0=중립(회색).
class PnlText extends StatelessWidget {
  final double amount;
  final double? rate;
  final TextStyle? style;

  // 수익/손실 색상 (TradingColors와 별개 — PnL 전용)
  static const _profitColor = Color(0xFF26A69A);
  static const _lossColor = Color(0xFFEF5350);
  static const _neutralColor = Color(0xFF9E9E9E);

  const PnlText({
    super.key,
    required this.amount,
    this.rate,
    this.style,
  });

  @override
  Widget build(BuildContext context) {
    final Color color;
    if (amount > 0) {
      color = _profitColor;
    } else if (amount < 0) {
      color = _lossColor;
    } else {
      color = _neutralColor;
    }

    final prefix = amount >= 0 ? '+' : '';
    final amountStr = '$prefix${FormatUtils.formatKrw(amount)}원';
    final rateStr = rate != null ? ' (${FormatUtils.formatRate(rate!)})' : '';

    return Text(
      '$amountStr$rateStr',
      style: (style ?? Theme.of(context).textTheme.bodyMedium)?.copyWith(
        color: color,
        fontFamily: 'Inter',
        fontFeatures: const [FontFeature.tabularFigures()],
        fontWeight: FontWeight.w600,
      ),
    );
  }
}
