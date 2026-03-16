import 'package:freezed_annotation/freezed_annotation.dart';

part 'orderbook.freezed.dart';
part 'orderbook.g.dart';

@freezed
class OrderbookEntry with _$OrderbookEntry {
  const factory OrderbookEntry({
    required double price,
    required double size,
  }) = _OrderbookEntry;

  factory OrderbookEntry.fromJson(Map<String, dynamic> json) =>
      _$OrderbookEntryFromJson(json);
}

@freezed
class Orderbook with _$Orderbook {
  const factory Orderbook({
    required String symbol,
    required List<OrderbookEntry> asks,
    required List<OrderbookEntry> bids,
  }) = _Orderbook;

  factory Orderbook.fromJson(Map<String, dynamic> json) =>
      _$OrderbookFromJson(json);
}
