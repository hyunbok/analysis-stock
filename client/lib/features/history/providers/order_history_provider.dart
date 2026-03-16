import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../models/order_history.dart';
import '../repositories/order_history_repository.dart';

part 'order_history_provider.g.dart';

/// 매매 내역 필터 상태
class OrderHistoryFilter {
  final int page;
  final String? status;
  final DateTime? from;
  final DateTime? to;

  const OrderHistoryFilter({
    this.page = 1,
    this.status,
    this.from,
    this.to,
  });
}

@riverpod
class OrderHistoryNotifier extends _$OrderHistoryNotifier {
  var _filter = const OrderHistoryFilter();

  @override
  Future<OrderHistoryPage> build() {
    return ref.watch(orderHistoryRepositoryProvider).getOrders(
          page: _filter.page,
          status: _filter.status,
          from: _filter.from,
          to: _filter.to,
        );
  }

  void applyFilter(OrderHistoryFilter filter) {
    _filter = filter;
    ref.invalidateSelf();
  }
}
