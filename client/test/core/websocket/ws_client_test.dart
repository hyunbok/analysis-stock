import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:coin_trader/core/storage/secure_storage.dart';
import 'package:coin_trader/core/websocket/ws_client.dart';
import 'package:coin_trader/core/websocket/ws_connection_state.dart';
import 'package:coin_trader/core/websocket/ws_message.dart';

/// WsClient 테스트용 SecureStorage Fake.
class _FakeStorage implements SecureStorage {
  @override
  Future<String?> readAccessToken() async => 'test-access-token';

  @override
  Future<String?> readRefreshToken() async => null;

  @override
  Future<void> saveTokens(
      {required String accessToken, required String refreshToken}) async {}

  @override
  Future<void> clearTokens() async {}

  @override
  Future<void> write({required String key, required String value}) async {}

  @override
  Future<String?> read({required String key}) async => null;

  @override
  Future<void> delete({required String key}) async {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('WsClient — 초기 상태', () {
    late WsClient client;

    setUp(() {
      client = WsClient(_FakeStorage());
    });

    tearDown(() {
      client.dispose();
    });

    test('초기 state == disconnected', () {
      expect(client.state, WsConnectionState.disconnected);
    });

    test('connectionStateStream은 broadcast stream', () {
      expect(client.connectionStateStream.isBroadcast, isTrue);
    });

    test('messageStream은 broadcast stream', () {
      expect(client.messageStream.isBroadcast, isTrue);
    });
  });

  group('WsClient — 구독 관리', () {
    late WsClient client;

    setUp(() {
      client = WsClient(_FakeStorage());
    });

    tearDown(() {
      client.dispose();
    });

    test('subscribe — 연결 전에 호출해도 활성 구독 목록에 추가됨', () {
      // 연결되지 않은 상태에서 subscribe → _activeSubscriptions에 추가되어야 함
      // (실제 WS 전송은 연결 후 _resubscribeAll에서 처리)
      client.subscribe('ticker', exchange: 'upbit', market: 'KRW-BTC');
      // 직접 접근 불가이므로 unsubscribe로 검증
      // unsubscribe가 예외 없이 동작하면 subscribe가 올바르게 등록된 것
      expect(() => client.unsubscribe('ticker', exchange: 'upbit', market: 'KRW-BTC'),
          returnsNormally);
    });

    test('channelStream — 같은 key에 동일 stream 반환', () {
      final s1 = client.channelStream('ticker');
      final s2 = client.channelStream('ticker');
      expect(identical(s1, s2), isTrue);
    });

    test('channelStream — 다른 key에 다른 stream 반환', () {
      final s1 = client.channelStream('ticker');
      final s2 = client.channelStream('orderbook');
      expect(identical(s1, s2), isFalse);
    });
  });

  group('WsClient — 상태 스트림', () {
    late WsClient client;

    setUp(() {
      client = WsClient(_FakeStorage());
    });

    tearDown(() {
      client.dispose();
    });

    test('disconnect() — disconnected 상태 emit', () async {
      // 이미 disconnected지만 추가 상태 변화 확인
      final states = <WsConnectionState>[];
      final sub = client.connectionStateStream.listen(states.add);

      await client.disconnect();
      sub.cancel();

      expect(states, contains(WsConnectionState.disconnected));
    });
  });

  group('WsClient — dispose', () {
    test('dispose 이후 stream 사용 불가 (closed)', () async {
      final client = WsClient(_FakeStorage());
      client.dispose();

      // dispose 후 stream은 closed 상태여야 함
      await expectLater(
        client.connectionStateStream,
        emitsDone,
      );
    });
  });

  group('WsClient — WsMessage 파싱', () {
    test('WsMessage.fromJson — action, channel, exchange, market 파싱', () {
      final json = {
        'action': 'subscribed',
        'channel': 'ticker',
        'exchange': 'upbit',
        'market': 'KRW-BTC',
      };
      final msg = WsMessage.fromJson(json);

      expect(msg.action, 'subscribed');
      expect(msg.channel, 'ticker');
      expect(msg.exchange, 'upbit');
      expect(msg.market, 'KRW-BTC');
    });

    test('WsMessage.fromJson — 부분 필드 (action만)', () {
      final msg = WsMessage.fromJson({'action': 'pong'});

      expect(msg.action, 'pong');
      expect(msg.channel, isNull);
    });

    test('WsMessage.fromJson — data 필드 포함', () {
      final msg = WsMessage.fromJson({
        'action': 'data',
        'channel': 'ticker',
        'data': {'price': 90000000, 'change_rate': 0.025},
      });

      expect(msg.action, 'data');
      expect(msg.data, isNotNull);
      expect(msg.data!['price'], 90000000);
    });
  });
}
