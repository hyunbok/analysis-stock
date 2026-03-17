import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/providers/market_state_provider.dart';
import '../../../shared/widgets/states/error_view.dart';
import '../../home/models/coin.dart';
import '../../home/providers/coin_list_provider.dart';
import '../../home/providers/watchlist_provider.dart';
import '../providers/order_form_provider.dart';
import '../providers/ticker_provider.dart';
import '../widgets/chart/timeframe_chips.dart';
import '../widgets/chart/trading_view_chart.dart';
import '../widgets/order/order_form.dart';
import '../widgets/orderbook/orderbook_widget.dart';
import '../widgets/trading_header.dart';

/// 트레이딩 탭 화면 — 코인 미선택 상태.
class TradingScreen extends StatelessWidget {
  const TradingScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('트레이딩')),
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.candlestick_chart_outlined,
              size: 64,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
            const SizedBox(height: 16),
            Text(
              '코인을 선택하세요',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 24),
            FilledButton.tonal(
              onPressed: () => context.go('/home'),
              child: const Text('홈에서 코인 선택'),
            ),
          ],
        ),
      ),
    );
  }
}

/// 코인 상세 트레이딩 화면.
class TradingDetailScreen extends ConsumerStatefulWidget {
  final String coinId;

  const TradingDetailScreen({super.key, required this.coinId});

  @override
  ConsumerState<TradingDetailScreen> createState() =>
      _TradingDetailScreenState();
}

class _TradingDetailScreenState extends ConsumerState<TradingDetailScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  String _interval = '1m';

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final selectedExchange = ref.watch(selectedExchangeProvider);
    final coinAsync = ref.watch(
      coinListProvider(exchange: selectedExchange),
    );

    return coinAsync.when(
      loading: () => Scaffold(
        appBar: AppBar(title: Text(widget.coinId)),
        body: const Center(child: CircularProgressIndicator()),
      ),
      error: (e, _) => Scaffold(
        appBar: AppBar(title: Text(widget.coinId)),
        body: ErrorView(error: e),
      ),
      data: (coins) {
        final coin = coins.firstWhere(
          (c) => c.id == widget.coinId,
          orElse: () => Coin(
            id: widget.coinId,
            symbol: widget.coinId,
            name: widget.coinId,
            exchange: selectedExchange,
            market: ref.read(selectedMarketProvider),
          ),
        );
        return _buildScreen(coin);
      },
    );
  }

  Widget _buildScreen(Coin coin) {
    final tickerAsync = ref.watch(
      tickerStreamProvider(
        exchange: coin.exchange,
        market: coin.market,
      ),
    );

    // ref.watch로 직접 파싱 — 스트림 변경 시 자동 리빌드
    final tickerData =
        tickerAsync.valueOrNull?.data as Map<String, dynamic>?;
    final price =
        (tickerData?['price'] as num?)?.toDouble() ?? coin.price ?? 0.0;
    final changeRate = (tickerData?['change_rate'] as num?)?.toDouble() ??
        coin.changeRate24h ??
        0.0;

    final watchlistAsync = ref.watch(watchlistProvider);
    final isFavorite = watchlistAsync.valueOrNull
            ?.any((c) => c.id == coin.id) ??
        false;
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        leading: const BackButton(),
        title: Text('${coin.symbol}/KRW'),
        actions: [
          IconButton(
            icon: Icon(isFavorite ? Icons.star : Icons.star_border),
            onPressed: () {
              if (isFavorite) {
                ref.read(watchlistProvider.notifier).remove(coin.id);
              } else {
                ref.read(watchlistProvider.notifier).add(coin.id);
              }
            },
          ),
          IconButton(
            icon: const Icon(Icons.more_vert),
            onPressed: () {},
          ),
        ],
      ),
      body: Column(
        children: [
          TradingHeader(price: price, changeRate: changeRate),
          TabBar(
            controller: _tabController,
            tabs: const [
              Tab(text: '차트'),
              Tab(text: '호가창'),
              Tab(text: '주문'),
            ],
          ),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                // 차트 탭
                Column(
                  children: [
                    Expanded(
                      child: TradingViewChart(
                        exchange: coin.exchange,
                        market: coin.market,
                        interval: _interval,
                        isDark: isDark,
                      ),
                    ),
                    TimeframeChips(
                      selectedInterval: _interval,
                      onChanged: (interval) =>
                          setState(() => _interval = interval),
                    ),
                  ],
                ),
                // 호가창 탭
                OrderbookWidget(coin: coin),
                // 주문 탭
                OrderForm(coin: coin),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
