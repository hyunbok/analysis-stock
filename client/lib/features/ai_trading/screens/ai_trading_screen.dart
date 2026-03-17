import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/constants/app_colors.dart';
import '../../../core/utils/format_utils.dart';
import '../../../shared/widgets/badges/ai_status_badge.dart';
import '../../../shared/widgets/badges/market_regime_chip.dart';
import '../../../shared/widgets/confirm_bottom_sheet.dart';
import '../../../shared/widgets/price/pnl_text.dart';
import '../../../shared/widgets/states/error_view.dart';
import '../models/ai_trading_config.dart';
import '../providers/ai_master_switch_provider.dart';
import '../providers/ai_trading_provider.dart';
import '../providers/ai_trading_stats_provider.dart';

/// AI 자동매매 대시보드.
class AiTradingScreen extends ConsumerWidget {
  const AiTradingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isMasterOn = ref.watch(aiMasterSwitchProvider);
    final configsAsync = ref.watch(aiTradingNotifierProvider);
    final statsAsync = ref.watch(aiTradingStatsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('AI 자동매매')),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(aiTradingNotifierProvider);
          ref.invalidate(aiTradingStatsProvider);
        },
        child: SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // AI 마스터 스위치
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('전체 AI 매매',
                                style: Theme.of(context).textTheme.titleMedium),
                            const SizedBox(height: 4),
                            AiStatusBadge(
                              status: isMasterOn
                                  ? AiStatus.on
                                  : AiStatus.off,
                            ),
                          ],
                        ),
                      ),
                      Switch(
                        value: isMasterOn,
                        onChanged: (value) async {
                          if (value) {
                            final configs =
                                configsAsync.valueOrNull ?? const [];
                            final totalMax = configs.fold<double>(
                                0, (sum, c) => sum + c.maxAmount);
                            final maxLabel = totalMax > 0
                                ? FormatUtils.formatKrw(totalMax)
                                : '0';
                            final confirmed = await ConfirmBottomSheet.show(
                              context,
                              title: 'AI 자동매매 시작',
                              message:
                                  'AI 자동매매를 시작합니다.\n최대 투자금: ${maxLabel}원',
                              confirmLabel: '시작',
                              confirmColor: AppColors.aiOn,
                            );
                            if (confirmed == true) {
                              ref.read(aiMasterSwitchProvider.notifier).set(true);
                            }
                          } else {
                            ref.read(aiMasterSwitchProvider.notifier).set(false);
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('AI 자동매매가 중지되었습니다')),
                            );
                          }
                        },
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              // 현재 장세
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('현재 장세',
                          style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          MarketRegimeChip(
                              regime: MarketRegime.trend, probability: 0.75),
                          const SizedBox(width: 8),
                          MarketRegimeChip(
                              regime: MarketRegime.range, probability: 0.20),
                          const SizedBox(width: 8),
                          MarketRegimeChip(
                              regime: MarketRegime.transition,
                              probability: 0.05),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '마지막 분석: ${FormatUtils.formatTime(DateTime.now())}',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color:
                                  Theme.of(context).colorScheme.onSurfaceVariant,
                            ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              // 오늘의 손익
              statsAsync.when(
                loading: () => const Card(
                  child: Padding(
                    padding: EdgeInsets.all(16),
                    child: Center(child: CircularProgressIndicator()),
                  ),
                ),
                error: (e, _) => Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text('통계 로딩 실패: $e'),
                  ),
                ),
                data: (stats) => Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('오늘의 손익',
                            style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 8),
                        PnlText(
                          amount: stats.totalPnl,
                          style:
                              Theme.of(context).textTheme.headlineSmall,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '거래수: ${stats.totalOrders}건 | 승률: ${(stats.winRate * 100).toStringAsFixed(1)}%',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              // 코인별 AI 설정
              Text('코인별 AI 설정',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              configsAsync.when(
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (e, _) => ErrorView(
                  error: e,
                  onRetry: () => ref.invalidate(aiTradingNotifierProvider),
                ),
                data: (configs) => Column(
                  children: configs
                      .map((config) => _CoinAiSettingTile(config: config))
                      .toList(),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CoinAiSettingTile extends ConsumerWidget {
  final AiTradingConfig config;

  const _CoinAiSettingTile({required this.config});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: CircleAvatar(
          child: Text(
            config.exchange.substring(0, 1).toUpperCase(),
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        ),
        title: Text(config.exchange),
        subtitle: Text('전략: ${config.strategy}'),
        trailing: Switch(
          value: config.isActive,
          onChanged: (value) {
            ref
                .read(aiTradingNotifierProvider.notifier)
                .toggle(config.id, isActive: value);
          },
        ),
      ),
    );
  }
}
