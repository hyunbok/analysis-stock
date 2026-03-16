import 'package:freezed_annotation/freezed_annotation.dart';

part 'ws_message.freezed.dart';
part 'ws_message.g.dart';

/// WebSocket 메시지 모델 (서버 WS Hub v1-12 프로토콜 기준).
///
/// Client→Server: action 필드 사용 (subscribe, unsubscribe, ping)
/// Server→Client: action(제어) 또는 channel(데이터) 필드 사용
@freezed
class WsMessage with _$WsMessage {
  const factory WsMessage({
    /// 제어 메시지 타입: subscribe|unsubscribe|ping|connected|subscribed|unsubscribed|pong|error|system
    String? action,

    /// 데이터 채널 식별자: ticker|orderbook|trades|my-orders|ai-signal|notification|price-alert|system
    String? channel,

    String? exchange,
    String? market,

    /// 서버 연결 ID (connected 메시지에서 수신)
    @JsonKey(name: 'conn_id') String? connId,

    /// 에러 코드 (error 메시지)
    String? code,

    /// 메시지 내용 (error, system 메시지)
    String? message,

    /// 채널 데이터 페이로드
    Map<String, dynamic>? data,

    String? timestamp,
  }) = _WsMessage;

  factory WsMessage.fromJson(Map<String, dynamic> json) =>
      _$WsMessageFromJson(json);
}

/// 서버 WS 채널 이름 상수.
abstract final class WsChannel {
  static const ticker = 'ticker';
  static const orderbook = 'orderbook';
  static const trades = 'trades';
  static const myOrders = 'my-orders';
  static const aiSignal = 'ai-signal';
  static const notification = 'notification';
  static const priceAlert = 'price-alert';
  static const system = 'system';
}
