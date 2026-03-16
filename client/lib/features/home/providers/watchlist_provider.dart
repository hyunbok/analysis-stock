import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../models/coin.dart';
import '../repositories/coin_repository.dart';

part 'watchlist_provider.g.dart';

@riverpod
class Watchlist extends _$Watchlist {
  @override
  Future<List<Coin>> build() {
    return ref.watch(coinRepositoryProvider).getWatchlist();
  }

  Future<void> add(String coinId) async {
    await ref.read(coinRepositoryProvider).addWatchlist(coinId);
    ref.invalidateSelf();
  }

  Future<void> remove(String watchlistId) async {
    await ref.read(coinRepositoryProvider).removeWatchlist(watchlistId);
    ref.invalidateSelf();
  }

  Future<void> reorder(List<String> watchlistIds) async {
    await ref.read(coinRepositoryProvider).reorderWatchlist(watchlistIds);
    ref.invalidateSelf();
  }
}
