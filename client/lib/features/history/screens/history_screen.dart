import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/utils/format_utils.dart';
import '../../../shared/widgets/states/empty_view.dart';
import '../../../shared/widgets/states/error_view.dart';
import '../../../shared/widgets/trade_history_tile.dart';
import '../models/order_history.dart';
import '../providers/order_history_provider.dart';

enum _PeriodFilter { thisMonth, lastMonth, custom }

/// 매매 내역 화면.
class HistoryScreen extends ConsumerStatefulWidget {
  const HistoryScreen({super.key});

  @override
  ConsumerState<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends ConsumerState<HistoryScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  _PeriodFilter _period = _PeriodFilter.thisMonth;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _applyPeriodFilter(_period);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  void _applyPeriodFilter(_PeriodFilter period) {
    final now = DateTime.now();
    final filter = switch (period) {
      _PeriodFilter.thisMonth => OrderHistoryFilter(
          from: DateTime(now.year, now.month, 1),
          to: now,
        ),
      _PeriodFilter.lastMonth => OrderHistoryFilter(
          from: DateTime(now.year, now.month - 1, 1),
          to: DateTime(now.year, now.month, 0),
        ),
      _PeriodFilter.custom => const OrderHistoryFilter(),
    };
    ref.read(orderHistoryNotifierProvider.notifier).applyFilter(filter);
  }

  @override
  Widget build(BuildContext context) {
    final historyAsync = ref.watch(orderHistoryNotifierProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('매매 내역')),
      body: Column(
        children: [
          // 기간 필터 칩
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                _PeriodChip(
                  label: '이번달',
                  isSelected: _period == _PeriodFilter.thisMonth,
                  onTap: () {
                    setState(() => _period = _PeriodFilter.thisMonth);
                    _applyPeriodFilter(_PeriodFilter.thisMonth);
                  },
                ),
                const SizedBox(width: 8),
                _PeriodChip(
                  label: '지난달',
                  isSelected: _period == _PeriodFilter.lastMonth,
                  onTap: () {
                    setState(() => _period = _PeriodFilter.lastMonth);
                    _applyPeriodFilter(_PeriodFilter.lastMonth);
                  },
                ),
                const SizedBox(width: 8),
                _PeriodChip(
                  label: '직접 선택',
                  isSelected: _period == _PeriodFilter.custom,
                  onTap: () {
                    setState(() => _period = _PeriodFilter.custom);
                    _applyPeriodFilter(_PeriodFilter.custom);
                  },
                ),
              ],
            ),
          ),
          // 요약 카드
          historyAsync.when(
            loading: () => const SizedBox.shrink(),
            error: (_, __) => const SizedBox.shrink(),
            data: (page) => _SummaryCard(orders: page.items),
          ),
          // 탭바
          TabBar(
            controller: _tabController,
            tabs: const [
              Tab(text: '주문 내역'),
              Tab(text: '체결 내역'),
            ],
          ),
          Expanded(
            child: historyAsync.when(
              loading: () =>
                  const Center(child: CircularProgressIndicator()),
              error: (e, _) => ErrorView(
                error: e,
                onRetry: () =>
                    ref.invalidate(orderHistoryNotifierProvider),
              ),
              data: (page) {
                if (page.items.isEmpty) {
                  return const EmptyView(
                    icon: Icons.receipt_long_outlined,
                    message: '매매 내역이 없습니다',
                  );
                }
                return TabBarView(
                  controller: _tabController,
                  children: [
                    // 주문 내역
                    _OrderHistoryList(orders: page.items),
                    // 체결 내역 (status == 'filled')
                    _OrderHistoryList(
                      orders: page.items
                          .where((o) => o.status == 'filled')
                          .toList(),
                    ),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _PeriodChip extends StatelessWidget {
  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  const _PeriodChip({
    required this.label,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return FilterChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (_) => onTap(),
      showCheckmark: false,
    );
  }
}

class _SummaryCard extends StatelessWidget {
  final List<OrderHistory> orders;

  const _SummaryCard({required this.orders});

  @override
  Widget build(BuildContext context) {
    final filled = orders.where((o) => o.status == 'filled').toList();
    final totalAmount =
        filled.fold<double>(0, (sum, o) => sum + o.total);

    return Card(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            Expanded(
              child: _StatItem(
                label: '총 거래액',
                value: '${FormatUtils.formatKrw(totalAmount)}원',
              ),
            ),
            Expanded(
              child: _StatItem(
                label: '거래수',
                value: '${filled.length}건',
              ),
            ),
            Expanded(
              child: _StatItem(
                label: '전체 주문',
                value: '${orders.length}건',
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatItem extends StatelessWidget {
  final String label;
  final String value;

  const _StatItem({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: Theme.of(context)
              .textTheme
              .titleSmall
              ?.copyWith(fontWeight: FontWeight.w600),
        ),
      ],
    );
  }
}

class _OrderHistoryList extends StatelessWidget {
  final List<OrderHistory> orders;

  const _OrderHistoryList({required this.orders});

  @override
  Widget build(BuildContext context) {
    if (orders.isEmpty) {
      return const EmptyView(
        icon: Icons.receipt_long_outlined,
        message: '내역이 없습니다',
      );
    }

    // 날짜별 그룹
    final grouped = <String, List<OrderHistory>>{};
    for (final order in orders) {
      final date = FormatUtils.formatDate(order.createdAt);
      grouped.putIfAbsent(date, () => []).add(order);
    }

    final dates = grouped.keys.toList()..sort((a, b) => b.compareTo(a));

    return ListView.builder(
      itemCount: dates.fold<int>(
          0, (sum, d) => sum + grouped[d]!.length + 1),
      itemBuilder: (context, flatIndex) {
        // 날짜 그룹 헤더와 아이템을 선형 인덱스로 접근
        int current = 0;
        for (final date in dates) {
          if (flatIndex == current) {
            return _DateGroupHeader(date: date);
          }
          current++;
          final items = grouped[date]!;
          if (flatIndex < current + items.length) {
            return TradeHistoryTile(
              order: items[flatIndex - current],
            );
          }
          current += items.length;
        }
        return const SizedBox.shrink();
      },
    );
  }
}

class _DateGroupHeader extends StatelessWidget {
  final String date;

  const _DateGroupHeader({required this.date});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Text(
        date,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
              fontWeight: FontWeight.w600,
            ),
      ),
    );
  }
}
