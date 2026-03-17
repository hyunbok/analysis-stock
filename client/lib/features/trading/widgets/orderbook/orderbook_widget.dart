import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/utils/format_utils.dart';
import '../../models/orderbook.dart';
import '../../providers/orderbook_provider.dart';
import '../../providers/order_form_provider.dart';
import '../../../home/models/coin.dart';
import 'orderbook_row.dart';

/// 호가창 전체 위젯 — 매도 호가 + 현재가 구분선 + 매수 호가.
class OrderbookWidget extends ConsumerWidget {
  final Coin coin;

  const OrderbookWidget({super.key, required this.coin});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    // WS 호가창 스트림 구독
    final orderbookStream = ref.watch(
      orderbookStreamProvider(exchange: coin.exchange, market: coin.market),
    );

    return orderbookStream.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('호가창 오류: $e')),
      data: (wsMsg) {
        // WsMessage에서 orderbook 데이터 파싱
        final orderbookData = wsMsg.data;
        List<OrderbookEntry> asks = [];
        List<OrderbookEntry> bids = [];

        if (orderbookData is Map<String, dynamic>) {
          final asksList = orderbookData['asks'] as List? ?? [];
          final bidsList = orderbookData['bids'] as List? ?? [];
          asks = asksList
              .map((e) => OrderbookEntry(
                    price: (e['price'] as num).toDouble(),
                    size: (e['size'] as num).toDouble(),
                  ))
              .toList();
          bids = bidsList
              .map((e) => OrderbookEntry(
                    price: (e['price'] as num).toDouble(),
                    size: (e['size'] as num).toDouble(),
                  ))
              .toList();
        }

        final displayAsks = asks.take(10).toList().reversed.toList();
        final displayBids = bids.take(10).toList();

        final allSizes = [...asks, ...bids].map((e) => e.size);
        final maxSize =
            allSizes.isNotEmpty ? allSizes.reduce((a, b) => a > b ? a : b) : 1.0;

        final currentPrice = coin.price ?? 0.0;

        return Column(
          children: [
            // 헤더
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '매도 잔량',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ),
                  Expanded(
                    child: Text(
                      '가격',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                      textAlign: TextAlign.right,
                    ),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            // 매도 호가 (역순 — 높은 가격이 위)
            Expanded(
              child: ListView.builder(
                reverse: false,
                itemCount: displayAsks.length,
                itemBuilder: (context, index) {
                  final entry = displayAsks[index];
                  return OrderbookRow(
                    price: entry.price,
                    size: entry.size,
                    maxSize: maxSize,
                    isBid: false,
                    onTap: () {
                      ref.read(orderFormProvider.notifier).setPrice(
                            entry.price.toStringAsFixed(0),
                          );
                    },
                  );
                },
              ),
            ),
            // 현재가 구분선
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 8),
              color: theme.colorScheme.surfaceContainerHighest,
              child: Center(
                child: Text(
                  '${FormatUtils.formatKrw(currentPrice)} 원',
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontFamily: 'Inter',
                    fontFeatures: const [FontFeature.tabularFigures()],
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ),
            // 매수 호가
            Expanded(
              child: ListView.builder(
                itemCount: displayBids.length,
                itemBuilder: (context, index) {
                  final entry = displayBids[index];
                  return OrderbookRow(
                    price: entry.price,
                    size: entry.size,
                    maxSize: maxSize,
                    isBid: true,
                    onTap: () {
                      ref.read(orderFormProvider.notifier).setPrice(
                            entry.price.toStringAsFixed(0),
                          );
                    },
                  );
                },
              ),
            ),
            const Divider(height: 1),
            // 푸터
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '매수 잔량',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}
