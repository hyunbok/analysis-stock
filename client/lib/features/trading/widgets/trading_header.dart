import 'package:flutter/material.dart';

import '../../../core/utils/format_utils.dart';
import '../../../shared/widgets/price/change_rate_text.dart';
import '../../../shared/widgets/price/price_text.dart';

/// 트레이딩 화면 현재가 고정 헤더 — 현재가 + 등락률.
class TradingHeader extends StatelessWidget {
  final double price;
  final double changeRate;
  final double? previousPrice;

  const TradingHeader({
    super.key,
    required this.price,
    required this.changeRate,
    this.previousPrice,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        border: Border(
          bottom: BorderSide(color: theme.colorScheme.outlineVariant),
        ),
      ),
      child: Row(
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              PriceText(
                price: price,
                previousPrice: previousPrice,
                style: theme.textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
                currencySuffix: '원',
              ),
              const SizedBox(height: 2),
              ChangeRateText(rate: changeRate),
            ],
          ),
        ],
      ),
    );
  }
}
