import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/dio_provider.dart';
import '../models/order.dart';

part 'order_repository.g.dart';

@riverpod
OrderRepository orderRepository(OrderRepositoryRef ref) {
  return OrderRepository(ref.watch(dioClientProvider));
}

class OrderRepository {
  final Dio _dio;

  const OrderRepository(this._dio);

  Future<Order> createOrder({
    required String exchangeAccountId,
    required String market,
    required String side,
    required String type,
    required double price,
    required double amount,
  }) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/api/v1/orders',
      data: {
        'exchange_account_id': exchangeAccountId,
        'market': market,
        'side': side,
        'type': type,
        'price': price,
        'amount': amount,
      },
    );
    return Order.fromJson(res.data!['data'] as Map<String, dynamic>);
  }

  Future<List<Order>> getOrders({String? status}) async {
    final res = await _dio.get<Map<String, dynamic>>(
      '/api/v1/orders',
      queryParameters: {if (status != null) 'status': status},
    );
    final items = res.data!['data']['items'] as List<dynamic>;
    return items
        .map((e) => Order.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> cancelOrder(String orderId) async {
    await _dio.delete<void>('/api/v1/orders/$orderId');
  }

  Future<void> batchCancel(List<String> orderIds) async {
    await _dio.post<void>(
      '/api/v1/orders/batch-cancel',
      data: {'ids': orderIds},
    );
  }
}
