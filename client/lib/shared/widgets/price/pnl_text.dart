import 'package:flutter/material.dart';

import '../../../core/constants/app_colors.dart';
import '../../../core/utils/format_utils.dart';

/// 손익 텍스트 위젯 — 양수=수익(초록), 음수=손실(빨강), 0=중립(회색).
class PnlText extends StatelessWidget {
  final double amount;
  final double? rate;
  final TextStyle? style;

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
      color = AppColors.profit;
    } else if (amount < 0) {
      color = AppColors.loss;
    } else {
      color = AppColors.neutral;
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
