import 'package:freezed_annotation/freezed_annotation.dart';

part 'coin.freezed.dart';
part 'coin.g.dart';

/// 코인 정보 모델.
///
/// 실시간 시세 필드 (price, changeRate24h, volume24h)는 optional.
/// - REST 조회 직후: null
/// - WS ticker 수신 후: 값 채워짐
@freezed
class Coin with _$Coin {
  const factory Coin({
    required String id,
    required String symbol,
    required String name,
    required String exchange,
    required String market,
    double? price,
    @JsonKey(name: 'change_rate_24h') double? changeRate24h,
    @JsonKey(name: 'volume_24h') double? volume24h,
  }) = _Coin;

  factory Coin.fromJson(Map<String, dynamic> json) => _$CoinFromJson(json);
}
