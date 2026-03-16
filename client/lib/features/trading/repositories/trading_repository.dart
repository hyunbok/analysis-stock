import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/dio_provider.dart';
import '../models/ticker.dart';
import '../models/orderbook.dart';

part 'trading_repository.g.dart';

@riverpod
TradingRepository tradingRepository(TradingRepositoryRef ref) {
  return TradingRepository(ref.watch(dioClientProvider));
}

/// 트레이딩 관련 REST API 호출 (시세, 호가).
///
/// 실시간 데이터(ticker, orderbook)는 WS Provider에서 처리.
/// 이 repository는 초기 스냅샷 조회에 사용된다.
class TradingRepository {
  final Dio _dio;

  const TradingRepository(this._dio);

  /// 코인 현재가 스냅샷 조회.
  Future<Ticker> getTicker({
    required String exchange,
    required String market,
  }) async {
    final res = await _dio.get<Map<String, dynamic>>(
      '/api/v1/market/ticker',
      queryParameters: {'exchange': exchange, 'market': market},
    );
    return Ticker.fromJson(res.data!['data'] as Map<String, dynamic>);
  }

  /// 호가 스냅샷 조회.
  Future<Orderbook> getOrderbook({
    required String exchange,
    required String market,
  }) async {
    final res = await _dio.get<Map<String, dynamic>>(
      '/api/v1/market/orderbook',
      queryParameters: {'exchange': exchange, 'market': market},
    );
    return Orderbook.fromJson(res.data!['data'] as Map<String, dynamic>);
  }
}
