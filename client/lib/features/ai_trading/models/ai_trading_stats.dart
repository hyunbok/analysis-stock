import 'package:freezed_annotation/freezed_annotation.dart';

part 'ai_trading_stats.freezed.dart';
part 'ai_trading_stats.g.dart';

@freezed
class AiTradingStats with _$AiTradingStats {
  const factory AiTradingStats({
    @JsonKey(name: 'total_pnl') required double totalPnl,
    @JsonKey(name: 'total_orders') required int totalOrders,
    @JsonKey(name: 'win_rate') required double winRate,
  }) = _AiTradingStats;

  factory AiTradingStats.fromJson(Map<String, dynamic> json) =>
      _$AiTradingStatsFromJson(json);
}
