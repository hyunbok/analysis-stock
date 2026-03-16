import 'package:freezed_annotation/freezed_annotation.dart';

part 'order_history.freezed.dart';
part 'order_history.g.dart';

@freezed
class OrderHistory with _$OrderHistory {
  const factory OrderHistory({
    required String id,
    required String exchange,
    required String market,
    required String side,
    required String type,
    required double price,
    required double amount,
    required double total,
    required String status,
    @JsonKey(name: 'created_at') required DateTime createdAt,
    @JsonKey(name: 'filled_at') DateTime? filledAt,
  }) = _OrderHistory;

  factory OrderHistory.fromJson(Map<String, dynamic> json) =>
      _$OrderHistoryFromJson(json);
}

@freezed
class OrderHistoryPage with _$OrderHistoryPage {
  const factory OrderHistoryPage({
    required List<OrderHistory> items,
    required int total,
    required int page,
    required int pages,
  }) = _OrderHistoryPage;

  factory OrderHistoryPage.fromJson(Map<String, dynamic> json) =>
      _$OrderHistoryPageFromJson(json);
}
