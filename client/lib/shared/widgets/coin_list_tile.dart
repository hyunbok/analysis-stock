import 'package:flutter/material.dart';

import '../../features/home/models/coin.dart';
import '../../core/utils/format_utils.dart';
import 'coin_icon.dart';
import 'price/change_rate_text.dart';
import 'price/price_text.dart';

/// 코인 목록 행 위젯 — 홈 화면 + 트레이딩 코인 선택 목록에서 공유.
///
/// [코인아이콘 36dp] [코인명 Bold / 심볼 Gray] [현재가 우측 / 등락률 색상]
class CoinListTile extends StatelessWidget {
  final Coin coin;
  final VoidCallback? onTap;
  final VoidCallback? onFavoriteToggle;
  final bool isFavorite;
  final double? previousPrice;

  const CoinListTile({
    super.key,
    required this.coin,
    this.onTap,
    this.onFavoriteToggle,
    this.isFavorite = false,
    this.previousPrice,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final price = coin.price;
    final changeRate = coin.changeRate24h;
    final volume = coin.volume24h;

    return ListTile(
      onTap: onTap,
      leading: CoinIcon(symbol: coin.symbol, size: 36),
      title: Text(
        coin.name,
        style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Text(
        coin.symbol,
        style: theme.textTheme.bodySmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (price != null)
            PriceText(
              price: price,
              previousPrice: previousPrice,
              style: theme.textTheme.titleSmall,
              currencySuffix: '원',
            )
          else
            Text(
              '- -',
              style: theme.textTheme.titleSmall,
            ),
          const SizedBox(height: 4),
          if (changeRate != null)
            ChangeRateText(rate: changeRate)
          else if (volume != null)
            Text(
              FormatUtils.formatVolume(volume),
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
