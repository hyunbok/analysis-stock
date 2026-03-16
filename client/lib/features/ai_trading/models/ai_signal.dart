import 'package:freezed_annotation/freezed_annotation.dart';

part 'ai_signal.freezed.dart';
part 'ai_signal.g.dart';

/// WS ai-signal 채널에서 수신하는 AI 매매 신호.
@freezed
class AiSignal with _$AiSignal {
  const factory AiSignal({
    @JsonKey(name: 'config_id') required String configId,
    required String signal, // 'buy' | 'sell' | 'hold'
    required double confidence,
    required String strategy,
    required String regime,
    required DateTime timestamp,
  }) = _AiSignal;

  factory AiSignal.fromJson(Map<String, dynamic> json) =>
      _$AiSignalFromJson(json);
}
