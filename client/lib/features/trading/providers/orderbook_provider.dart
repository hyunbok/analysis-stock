import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/ws_provider.dart';
import '../../../core/websocket/ws_message.dart';

part 'orderbook_provider.g.dart';

/// 실시간 호가창 스트림 (WS orderbook 채널).
@riverpod
Stream<WsMessage> orderbookStream(
  OrderbookStreamRef ref, {
  required String exchange,
  required String market,
}) {
  final client = ref.watch(wsClientProvider);

  ref.onDispose(() {
    client.unsubscribe(WsChannel.orderbook, exchange: exchange, market: market);
  });

  client.subscribe(WsChannel.orderbook, exchange: exchange, market: market);

  return client.channelStream(WsChannel.orderbook).where(
        (msg) => msg.exchange == exchange && msg.market == market,
      );
}
