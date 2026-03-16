import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/dio_provider.dart';
import '../models/coin.dart';

part 'coin_repository.g.dart';

@riverpod
CoinRepository coinRepository(CoinRepositoryRef ref) {
  return CoinRepository(ref.watch(dioClientProvider));
}

class CoinRepository {
  final Dio _dio;

  const CoinRepository(this._dio);

  Future<List<Coin>> getCoins({
    String? query,
    String? exchange,
    int page = 1,
    int size = 20,
  }) async {
    final res = await _dio.get<Map<String, dynamic>>(
      '/api/v1/coins',
      queryParameters: {
        if (query != null) 'q': query,
        if (exchange != null) 'exchange': exchange,
        'page': page,
        'size': size,
      },
    );
    final items = res.data!['data']['items'] as List<dynamic>;
    return items
        .map((e) => Coin.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Coin> getCoin(String coinId) async {
    final res = await _dio
        .get<Map<String, dynamic>>('/api/v1/coins/$coinId');
    return Coin.fromJson(res.data!['data'] as Map<String, dynamic>);
  }

  Future<List<Coin>> getWatchlist({String? exchangeAccountId}) async {
    final res = await _dio.get<Map<String, dynamic>>(
      '/api/v1/watchlist',
      queryParameters: {
        if (exchangeAccountId != null)
          'exchange_account_id': exchangeAccountId,
      },
    );
    final items = res.data!['data'] as List<dynamic>;
    return items
        .map((e) => Coin.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> addWatchlist(String coinId) async {
    await _dio.post<void>(
      '/api/v1/watchlist',
      data: {'coin_id': coinId},
    );
  }

  Future<void> removeWatchlist(String watchlistId) async {
    await _dio.delete<void>('/api/v1/watchlist/$watchlistId');
  }

  Future<void> reorderWatchlist(List<String> watchlistIds) async {
    await _dio.put<void>(
      '/api/v1/watchlist/reorder',
      data: {'ids': watchlistIds},
    );
  }
}
