import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/ws_provider.dart';
import '../../../core/websocket/ws_message.dart';

part 'ticker_provider.g.dart';

/// 트레이딩 화면 실시간 시세 스트림 (WS ticker 채널).
@riverpod
Stream<WsMessage> tickerStream(
  TickerStreamRef ref, {
  required String exchange,
  required String market,
}) {
  final client = ref.watch(wsClientProvider);

  ref.onDispose(() {
    client.unsubscribe(WsChannel.ticker, exchange: exchange, market: market);
  });

  client.subscribe(WsChannel.ticker, exchange: exchange, market: market);

  return client.channelStream(WsChannel.ticker).where(
        (msg) => msg.exchange == exchange && msg.market == market,
      );
}
