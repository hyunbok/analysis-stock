import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../models/order.dart';
import '../repositories/order_repository.dart';

part 'order_provider.g.dart';

@riverpod
class OrderNotifier extends _$OrderNotifier {
  @override
  AsyncValue<Order?> build() => const AsyncData(null);

  Future<void> createOrder({
    required String exchangeAccountId,
    required String market,
    required String side,
    required String type,
    required double price,
    required double amount,
  }) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() => ref
        .read(orderRepositoryProvider)
        .createOrder(
          exchangeAccountId: exchangeAccountId,
          market: market,
          side: side,
          type: type,
          price: price,
          amount: amount,
        ));
  }
}
