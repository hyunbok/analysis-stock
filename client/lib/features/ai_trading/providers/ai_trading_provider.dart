import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/ws_provider.dart';
import '../../../core/websocket/ws_message.dart';
import '../models/ai_trading_config.dart';
import '../repositories/ai_trading_repository.dart';

part 'ai_trading_provider.g.dart';

@riverpod
class AiTradingNotifier extends _$AiTradingNotifier {
  @override
  Future<List<AiTradingConfig>> build() {
    return ref.watch(aiTradingRepositoryProvider).getConfigs();
  }

  Future<void> toggle(String configId, {required bool isActive}) async {
    await ref
        .read(aiTradingRepositoryProvider)
        .toggleActivation(configId, isActive: isActive);
    ref.invalidateSelf();
  }
}

/// AI 매매 신호 실시간 스트림 (WS ai-signal 채널).
@riverpod
Stream<WsMessage> aiSignalStream(
  AiSignalStreamRef ref,
  String configId,
) {
  final client = ref.watch(wsClientProvider);

  ref.onDispose(() {
    client.unsubscribe(WsChannel.aiSignal);
  });

  client.subscribe(WsChannel.aiSignal);

  return client.channelStream(WsChannel.aiSignal);
}
