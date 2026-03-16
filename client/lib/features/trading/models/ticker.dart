import 'package:freezed_annotation/freezed_annotation.dart';

part 'ticker.freezed.dart';
part 'ticker.g.dart';

@freezed
class Ticker with _$Ticker {
  const factory Ticker({
    required String symbol,
    required double price,
    @JsonKey(name: 'change_rate_24h') required double changeRate24h,
    @JsonKey(name: 'volume_24h') required double volume24h,
    required DateTime timestamp,
  }) = _Ticker;

  factory Ticker.fromJson(Map<String, dynamic> json) => _$TickerFromJson(json);
}
