import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/dio_provider.dart';
import '../models/ai_trading_config.dart';
import '../models/ai_trading_stats.dart';

part 'ai_trading_repository.g.dart';

@riverpod
AiTradingRepository aiTradingRepository(AiTradingRepositoryRef ref) {
  return AiTradingRepository(ref.watch(dioClientProvider));
}

class AiTradingRepository {
  final Dio _dio;

  const AiTradingRepository(this._dio);

  Future<List<AiTradingConfig>> getConfigs() async {
    final res =
        await _dio.get<Map<String, dynamic>>('/api/v1/ai-trading/configs');
    final items = res.data!['data'] as List<dynamic>;
    return items
        .map((e) => AiTradingConfig.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<AiTradingConfig> toggleActivation(
    String configId, {
    required bool isActive,
  }) async {
    final res = await _dio.patch<Map<String, dynamic>>(
      '/api/v1/ai-trading/configs/$configId/activation',
      data: {'is_active': isActive},
    );
    return AiTradingConfig.fromJson(
        res.data!['data'] as Map<String, dynamic>);
  }

  Future<bool> getMasterSwitch() async {
    final res = await _dio
        .get<Map<String, dynamic>>('/api/v1/ai-trading/master-switch');
    return res.data!['data']['is_active'] as bool;
  }

  Future<void> setMasterSwitch(bool isActive) async {
    await _dio.patch<void>(
      '/api/v1/ai-trading/master-switch',
      data: {'is_active': isActive},
    );
  }

  Future<AiTradingStats> getTotalStats() async {
    final res = await _dio
        .get<Map<String, dynamic>>('/api/v1/ai-trading/stats/total');
    return AiTradingStats.fromJson(
        res.data!['data'] as Map<String, dynamic>);
  }
}
