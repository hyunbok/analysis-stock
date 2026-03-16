import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../websocket/ws_client.dart';
import '../websocket/ws_connection_state.dart';
import 'storage_provider.dart';

part 'ws_provider.g.dart';

/// [WsClient] 인스턴스를 제공한다.
///
/// 앱 생애주기 동안 단일 인스턴스 유지 (keepAlive: true).
/// 실제 연결은 [authStateProvider]에서 로그인 성공 시 호출한다.
@Riverpod(keepAlive: true)
WsClient wsClient(WsClientRef ref) {
  final storage = ref.watch(secureStorageProvider);
  final client = WsClient(storage);
  ref.onDispose(client.dispose);
  return client;
}

/// WebSocket 연결 상태 스트림.
///
/// UI에서 연결 상태 인디케이터를 표시할 때 사용:
/// ```dart
/// final state = ref.watch(wsConnectionStateProvider).valueOrNull
///     ?? WsConnectionState.disconnected;
/// ```
@Riverpod(keepAlive: true)
Stream<WsConnectionState> wsConnectionState(WsConnectionStateRef ref) {
  final client = ref.watch(wsClientProvider);
  return client.connectionStateStream;
}
