import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../models/exchange_account.dart';
import '../repositories/exchange_repository.dart';

part 'exchange_provider.g.dart';

@riverpod
class ExchangeList extends _$ExchangeList {
  @override
  Future<List<ExchangeAccount>> build() {
    return ref.watch(exchangeRepositoryProvider).getExchanges();
  }

  Future<void> delete(String id) async {
    await ref.read(exchangeRepositoryProvider).deleteExchange(id);
    ref.invalidateSelf();
  }

  Future<void> verify(String id) async {
    await ref.read(exchangeRepositoryProvider).verifyExchange(id);
    ref.invalidateSelf();
  }
}
