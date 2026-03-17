import 'package:flutter/material.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'order_form_provider.g.dart';

enum OrderSide { buy, sell }

enum OrderType { limit, market }

@immutable
class OrderFormState {
  final OrderSide side;
  final OrderType type;
  final String price;
  final String quantity;

  const OrderFormState({
    this.side = OrderSide.buy,
    this.type = OrderType.limit,
    this.price = '',
    this.quantity = '',
  });

  OrderFormState copyWith({
    OrderSide? side,
    OrderType? type,
    String? price,
    String? quantity,
  }) =>
      OrderFormState(
        side: side ?? this.side,
        type: type ?? this.type,
        price: price ?? this.price,
        quantity: quantity ?? this.quantity,
      );
}

/// 주문 폼 상태 Provider — 탭 전환 간 상태 유지.
@riverpod
class OrderForm extends _$OrderForm {
  KeepAliveLink? _keepAlive;

  @override
  OrderFormState build() {
    _keepAlive = ref.keepAlive();
    ref.onDispose(() => _keepAlive?.close());
    return const OrderFormState();
  }

  void setSide(OrderSide side) => state = state.copyWith(side: side);
  void setType(OrderType type) => state = state.copyWith(type: type);
  void setPrice(String price) => state = state.copyWith(price: price);
  void setQuantity(String quantity) => state = state.copyWith(quantity: quantity);

  void reset() {
    state = const OrderFormState();
    _keepAlive?.close();
    _keepAlive = null;
  }
}
