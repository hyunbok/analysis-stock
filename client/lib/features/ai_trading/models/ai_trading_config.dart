import 'package:freezed_annotation/freezed_annotation.dart';

part 'ai_trading_config.freezed.dart';
part 'ai_trading_config.g.dart';

@freezed
class AiTradingConfig with _$AiTradingConfig {
  const factory AiTradingConfig({
    required String id,
    @Default(false) bool isActive,
    required String exchange,
    required String strategy,
    @JsonKey(name: 'max_amount') required double maxAmount,
  }) = _AiTradingConfig;

  factory AiTradingConfig.fromJson(Map<String, dynamic> json) =>
      _$AiTradingConfigFromJson(json);
}
