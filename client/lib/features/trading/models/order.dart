import 'package:freezed_annotation/freezed_annotation.dart';

part 'order.freezed.dart';
part 'order.g.dart';

@freezed
class Order with _$Order {
  const factory Order({
    required String id,
    required String side, // 'buy' | 'sell'
    required String type, // 'limit' | 'market'
    required double price,
    required double amount,
    required String status, // 'open' | 'filled' | 'cancelled'
    @JsonKey(name: 'created_at') required DateTime createdAt,
  }) = _Order;

  factory Order.fromJson(Map<String, dynamic> json) => _$OrderFromJson(json);
}
