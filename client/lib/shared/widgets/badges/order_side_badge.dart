import 'package:flutter/material.dart';

import '../../../app/theme.dart';

enum OrderSide { buy, sell }

/// 매수/매도 뱃지.
class OrderSideBadge extends StatelessWidget {
  final OrderSide side;

  const OrderSideBadge({super.key, required this.side});

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<TradingColors>()!;
    final color = side == OrderSide.buy ? colors.buyColor : colors.sellColor;
    final label = side == OrderSide.buy ? '매수' : '매도';

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withOpacity(0.4)),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: color,
              fontWeight: FontWeight.w600,
            ),
      ),
    );
  }
}
