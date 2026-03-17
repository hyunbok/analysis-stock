import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/utils/format_utils.dart';
import '../../../shared/widgets/coin_icon.dart';
import '../../../shared/widgets/price/pnl_text.dart';
import '../../../shared/widgets/states/error_view.dart';
import '../models/portfolio_summary.dart';
import '../providers/portfolio_provider.dart';

/// 자산 화면 — 거래소별 총 자산, 코인별 보유량/수익률.
class PortfolioScreen extends ConsumerWidget {
  const PortfolioScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final portfolioAsync = ref.watch(portfolioProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('자산')),
      body: portfolioAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorView(
          error: e,
          onRetry: () => ref.invalidate(portfolioProvider),
        ),
        data: (summary) => RefreshIndicator(
          onRefresh: () async => ref.invalidate(portfolioProvider),
          child: SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // 총 자산 카드
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('총 자산',
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant,
                            )),
                        const SizedBox(height: 8),
                        Text(
                          '${FormatUtils.formatKrw(summary.totalAsset)} 원',
                          style: Theme.of(context)
                              .textTheme
                              .headlineMedium
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 4),
                        PnlText(amount: summary.totalPnl),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                // 거래소별 자산
                ...summary.exchanges.map(
                  (ep) => _ExchangePortfolioSection(portfolio: ep),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ExchangePortfolioSection extends StatelessWidget {
  final ExchangePortfolio portfolio;

  const _ExchangePortfolioSection({required this.portfolio});

  String get _exchangeLabel => switch (portfolio.exchange.toLowerCase()) {
        'upbit' => '업비트',
        'coinone' => '코인원',
        _ => portfolio.exchange,
      };

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(_exchangeLabel,
              style: Theme.of(context).textTheme.titleMedium
                  ?.copyWith(fontWeight: FontWeight.w600)),
        ),
        ...portfolio.holdings.map((h) => _CoinHoldingTile(holding: h)),
        const SizedBox(height: 8),
      ],
    );
  }
}

class _CoinHoldingTile extends StatelessWidget {
  final CoinHolding holding;

  const _CoinHoldingTile({required this.holding});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            CoinIcon(symbol: holding.symbol, size: 36),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(holding.symbol,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w600)),
                  Text(
                    '보유: ${FormatUtils.formatCoinAmount(holding.amount)}',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  '${FormatUtils.formatKrw(holding.currentPrice)}원',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontFamily: 'Inter',
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
                Text(
                  '평균: ${FormatUtils.formatKrw(holding.avgBuyPrice)}원',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                PnlText(rate: holding.pnlRate, amount: 0),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
