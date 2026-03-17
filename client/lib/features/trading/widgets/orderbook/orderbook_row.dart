import 'package:flutter/material.dart';

import '../../../../app/theme.dart';
import '../../../../core/utils/format_utils.dart';

/// 호가창 행 — 가격 + 잔량 + 비율 컬러 바.
class OrderbookRow extends StatelessWidget {
  final double price;
  final double size;
  final double maxSize;
  final bool isBid;
  final VoidCallback? onTap;

  const OrderbookRow({
    super.key,
    required this.price,
    required this.size,
    required this.maxSize,
    required this.isBid,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<TradingColors>()!;
    final color = isBid ? colors.buyColor : colors.sellColor;
    final fillRatio = maxSize > 0 ? (size / maxSize).clamp(0.0, 1.0) : 0.0;

    return GestureDetector(
      onTap: onTap,
      child: SizedBox(
        height: 32,
        child: Stack(
          children: [
            // 컬러 바 배경
            Positioned(
              right: 0,
              top: 0,
              bottom: 0,
              child: FractionallySizedBox(
                widthFactor: fillRatio,
                child: Container(
                  color: color.withOpacity(0.1),
                ),
              ),
            ),
            // 텍스트 레이어
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Row(
                children: [
                  if (!isBid) ...[
                    Expanded(
                      child: Text(
                        FormatUtils.formatCoinAmount(size),
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              fontFamily: 'Inter',
                              fontFeatures: const [FontFeature.tabularFigures()],
                            ),
                        textAlign: TextAlign.left,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        FormatUtils.formatKrw(price),
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: color,
                              fontFamily: 'Inter',
                              fontFeatures: const [FontFeature.tabularFigures()],
                              fontWeight: FontWeight.w600,
                            ),
                        textAlign: TextAlign.right,
                      ),
                    ),
                  ] else ...[
                    Expanded(
                      child: Text(
                        FormatUtils.formatKrw(price),
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: color,
                              fontFamily: 'Inter',
                              fontFeatures: const [FontFeature.tabularFigures()],
                              fontWeight: FontWeight.w600,
                            ),
                        textAlign: TextAlign.left,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        FormatUtils.formatCoinAmount(size),
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              fontFamily: 'Inter',
                              fontFeatures: const [FontFeature.tabularFigures()],
                            ),
                        textAlign: TextAlign.right,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
