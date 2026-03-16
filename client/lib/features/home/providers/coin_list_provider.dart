import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../models/coin.dart';
import '../repositories/coin_repository.dart';

part 'coin_list_provider.g.dart';

/// 코인 목록 검색 파라미터
class CoinListParams {
  final String? query;
  final String? exchange;
  final int page;
  final int size;

  const CoinListParams({
    this.query,
    this.exchange,
    this.page = 1,
    this.size = 20,
  });
}

@riverpod
Future<List<Coin>> coinList(
  CoinListRef ref, {
  String? query,
  String? exchange,
  int page = 1,
  int size = 20,
}) {
  return ref.watch(coinRepositoryProvider).getCoins(
        query: query,
        exchange: exchange,
        page: page,
        size: size,
      );
}
