import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/dio_provider.dart';
import '../models/order_history.dart';

part 'order_history_repository.g.dart';

@riverpod
OrderHistoryRepository orderHistoryRepository(
    OrderHistoryRepositoryRef ref) {
  return OrderHistoryRepository(ref.watch(dioClientProvider));
}

class OrderHistoryRepository {
  final Dio _dio;

  const OrderHistoryRepository(this._dio);

  Future<OrderHistoryPage> getOrders({
    int page = 1,
    int size = 20,
    String? status,
    DateTime? from,
    DateTime? to,
  }) async {
    final res = await _dio.get<Map<String, dynamic>>(
      '/api/v1/orders',
      queryParameters: {
        'page': page,
        'size': size,
        if (status != null) 'status': status,
        if (from != null) 'from': from.toIso8601String(),
        if (to != null) 'to': to.toIso8601String(),
      },
    );
    return OrderHistoryPage.fromJson(
        res.data!['data'] as Map<String, dynamic>);
  }
}
