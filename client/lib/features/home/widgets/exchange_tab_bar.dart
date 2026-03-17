import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers/market_state_provider.dart';

/// 거래소 선택 탭 바 — 업비트 / 코인원.
class ExchangeTabBar extends ConsumerWidget {
  final TabController tabController;

  const ExchangeTabBar({super.key, required this.tabController});

  static const _exchanges = ['upbit', 'coinone'];
  static const _labels = ['업비트', '코인원'];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return TabBar(
      controller: tabController,
      tabs: _labels
          .map((label) => Tab(text: label))
          .toList(),
      onTap: (index) {
        ref.read(selectedExchangeProvider.notifier).select(_exchanges[index]);
      },
    );
  }
}
