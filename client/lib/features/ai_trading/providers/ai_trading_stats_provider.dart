import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../models/ai_trading_stats.dart';
import '../repositories/ai_trading_repository.dart';

part 'ai_trading_stats_provider.g.dart';

@riverpod
Future<AiTradingStats> aiTradingStats(AiTradingStatsRef ref) {
  return ref.watch(aiTradingRepositoryProvider).getTotalStats();
}
