import 'package:flutter/material.dart';

import '../../core/utils/format_utils.dart';
import '../../features/history/models/order_history.dart';
import 'badges/order_side_badge.dart';
import 'coin_icon.dart';
import 'price/pnl_text.dart';

/// 매매 내역 행 위젯 — 내역 + AI 로그 화면에서 공유.
class TradeHistoryTile extends StatelessWidget {
  final OrderHistory order;
  final double? pnl;
  final double? pnlRate;
  final bool isAiTrade;
  final VoidCallback? onTap;

  const TradeHistoryTile({
    super.key,
    required this.order,
    this.pnl,
    this.pnlRate,
    this.isAiTrade = false,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final side =
        order.side.toLowerCase() == 'buy' ? OrderSide.buy : OrderSide.sell;
    final coinSymbol = order.market.split('-').last;

    return ListTile(
      onTap: onTap,
      leading: CoinIcon(symbol: coinSymbol, size: 36),
      title: Row(
        children: [
          Text(
            coinSymbol,
            style: theme.textTheme.titleSmall
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(width: 8),
          OrderSideBadge(side: side),
          if (isAiTrade) ...[
            const SizedBox(width: 6),
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: const Color(0xFF00BCD4).withOpacity(0.15),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                'AI',
                style: theme.textTheme.labelSmall?.copyWith(
                  color: const Color(0xFF00BCD4),
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ],
      ),
      subtitle: Text(
        '${FormatUtils.formatKrw(order.price)} × ${FormatUtils.formatCoinAmount(order.amount)}',
        style: theme.textTheme.bodySmall?.copyWith(
          fontFamily: 'Inter',
          fontFeatures: const [FontFeature.tabularFigures()],
        ),
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (pnl != null)
            PnlText(amount: pnl!, rate: pnlRate)
          else
            Text(
              FormatUtils.formatKrw(order.total),
              style: theme.textTheme.bodySmall,
            ),
          const SizedBox(height: 4),
          Text(
            FormatUtils.formatTime(order.createdAt),
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
    );
  }
}
