import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/providers/market_state_provider.dart';
import '../../../shared/widgets/app_search_bar.dart';
import '../../../shared/widgets/coin_list_tile.dart';
import '../../../shared/widgets/connection/ws_connection_banner.dart';
import '../../../shared/widgets/loading/shimmer_list.dart';
import '../../../shared/widgets/states/empty_view.dart';
import '../../../shared/widgets/states/error_view.dart';
import '../models/coin.dart';
import '../providers/coin_list_provider.dart';
import '../providers/watchlist_provider.dart';
import '../widgets/exchange_tab_bar.dart';

enum _CoinSort { name, price, change, volume }

/// 홈 화면 — 거래소 탭 + 관심 코인 실시간 시세 + 코인 검색.
class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  String _searchQuery = '';
  bool _isSearching = false;
  _CoinSort _sort = _CoinSort.price;
  bool _sortAscending = false;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  List<Coin> _sortCoins(List<Coin> coins) {
    final sorted = List<Coin>.from(coins);
    sorted.sort((a, b) {
      int cmp;
      switch (_sort) {
        case _CoinSort.name:
          cmp = a.name.compareTo(b.name);
        case _CoinSort.price:
          cmp = (a.price ?? 0).compareTo(b.price ?? 0);
        case _CoinSort.change:
          cmp = (a.changeRate24h ?? 0).compareTo(b.changeRate24h ?? 0);
        case _CoinSort.volume:
          cmp = (a.volume24h ?? 0).compareTo(b.volume24h ?? 0);
      }
      return _sortAscending ? cmp : -cmp;
    });
    return sorted;
  }

  void _toggleSort(_CoinSort sort) {
    setState(() {
      if (_sort == sort) {
        _sortAscending = !_sortAscending;
      } else {
        _sort = sort;
        _sortAscending = false;
      }
    });
  }

  Widget _buildSortHeader() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          _SortButton(
            label: '코인명',
            isActive: _sort == _CoinSort.name,
            ascending: _sortAscending,
            onTap: () => _toggleSort(_CoinSort.name),
          ),
          const Spacer(),
          _SortButton(
            label: '현재가',
            isActive: _sort == _CoinSort.price,
            ascending: _sortAscending,
            onTap: () => _toggleSort(_CoinSort.price),
          ),
          const SizedBox(width: 16),
          _SortButton(
            label: '변동률',
            isActive: _sort == _CoinSort.change,
            ascending: _sortAscending,
            onTap: () => _toggleSort(_CoinSort.change),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final selectedExchange = ref.watch(selectedExchangeProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('CoinTrader'),
        actions: [
          const WsConnectionIndicator(),
          IconButton(
            icon: const Icon(Icons.notifications_outlined),
            onPressed: () => context.push('/more/notifications'),
          ),
          IconButton(
            icon: const Icon(Icons.person_outline),
            onPressed: () => context.push('/more/profile'),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(48),
          child: ExchangeTabBar(tabController: _tabController),
        ),
      ),
      body: Column(
        children: [
          const WsConnectionBanner(),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: AppSearchBar(
              hintText: '코인 검색...',
              onChanged: (query) =>
                  setState(() => _searchQuery = query),
              onTap: () => setState(() => _isSearching = true),
            ),
          ),
          _buildSortHeader(),
          Expanded(
            child: _isSearching && _searchQuery.isNotEmpty
                ? _buildSearchResults(selectedExchange)
                : _buildWatchlist(),
          ),
        ],
      ),
    );
  }

  Widget _buildWatchlist() {
    final watchlistAsync = ref.watch(watchlistProvider);
    return watchlistAsync.when(
      loading: () => const ShimmerList(count: 8),
      error: (e, _) => ErrorView(
        error: e,
        onRetry: () => ref.invalidate(watchlistProvider),
      ),
      data: (coins) {
        if (coins.isEmpty) {
          return const EmptyView(
            icon: Icons.star_outline,
            message: '관심 코인을 추가해보세요',
          );
        }
        final sorted = _sortCoins(coins);
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(watchlistProvider),
          child: ListView.separated(
            itemCount: sorted.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, index) {
              final coin = sorted[index];
              return CoinListTile(
                coin: coin,
                isFavorite: true,
                onTap: () {
                  ref.read(selectedMarketProvider.notifier).select(coin.market);
                  context.push('/trading/${coin.id}');
                },
                onFavoriteToggle: () {
                  ref.read(watchlistProvider.notifier).remove(coin.id);
                },
              );
            },
          ),
        );
      },
    );
  }

  Widget _buildSearchResults(String exchange) {
    final coinListAsync = ref.watch(
      coinListProvider(exchange: exchange, query: _searchQuery),
    );
    return coinListAsync.when(
      loading: () => const ShimmerList(count: 8),
      error: (e, _) => ErrorView(error: e),
      data: (coins) {
        if (coins.isEmpty) {
          return const EmptyView(message: '코인이 없습니다');
        }
        return ListView.separated(
          itemCount: coins.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (context, index) {
            final coin = coins[index];
            return CoinListTile(
              coin: coin,
              onTap: () {
                ref.read(selectedMarketProvider.notifier).select(coin.market);
                context.push('/trading/${coin.id}');
              },
              onFavoriteToggle: () {
                ref.read(watchlistProvider.notifier).add(coin.id);
              },
            );
          },
        );
      },
    );
  }
}

class _SortButton extends StatelessWidget {
  final String label;
  final bool isActive;
  final bool ascending;
  final VoidCallback onTap;

  const _SortButton({
    required this.label,
    required this.isActive,
    required this.ascending,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: isActive
                      ? Theme.of(context).colorScheme.primary
                      : Theme.of(context).colorScheme.onSurfaceVariant,
                  fontWeight:
                      isActive ? FontWeight.w600 : FontWeight.normal,
                ),
          ),
          if (isActive)
            Icon(
              ascending ? Icons.arrow_upward : Icons.arrow_downward,
              size: 12,
              color: Theme.of(context).colorScheme.primary,
            ),
        ],
      ),
    );
  }
}
