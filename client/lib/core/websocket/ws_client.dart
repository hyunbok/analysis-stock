import 'dart:async';
import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../constants/constants.dart';
import '../storage/secure_storage.dart';
import 'ws_connection_state.dart';
import 'ws_message.dart';

/// WebSocket 연결, 구독/해제, 자동 재연결, 하트비트를 관리한다.
///
/// 재연결 전략: 지수 백오프 (1→2→4→8→16→30초 max)
/// Heartbeat:  30초마다 ping, 10초 내 pong 미수신 시 강제 재연결
/// 백그라운드: [AppLifecycleState.paused] 시 disconnect, [resumed] 시 reconnect
class WsClient with WidgetsBindingObserver {
  final SecureStorage _storage;

  WsClient(this._storage) {
    WidgetsBinding.instance.addObserver(this);
  }

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _channelSub;

  final _messageCtrl = StreamController<WsMessage>.broadcast();
  final _stateCtrl = StreamController<WsConnectionState>.broadcast();
  final Map<String, StreamController<WsMessage>> _channelCtrlMap = {};

  /// 활성 구독 목록 — 재연결 시 자동 재구독
  final Set<({String channel, String? exchange, String? market})>
      _activeSubscriptions = {};

  WsConnectionState _state = WsConnectionState.disconnected;
  int _retryCount = 0;
  Timer? _reconnectTimer;
  Timer? _heartbeatTimer;
  Timer? _pongTimeoutTimer;

  // ── 공개 스트림 ─────────────────────────────────────────────

  Stream<WsConnectionState> get connectionStateStream => _stateCtrl.stream;

  /// 모든 메시지 스트림 (채널 필터 없음)
  Stream<WsMessage> get messageStream => _messageCtrl.stream;

  WsConnectionState get state => _state;

  /// 특정 채널의 데이터 메시지 스트림.
  ///
  /// [StreamProvider.family]에서 사용:
  /// ```dart
  /// ref.watch(wsClientProvider).channelStream(WsChannel.ticker)
  /// ```
  Stream<WsMessage> channelStream(String channelKey) {
    return _channelCtrlMap
        .putIfAbsent(channelKey, () => StreamController<WsMessage>.broadcast())
        .stream;
  }

  // ── 연결 관리 ───────────────────────────────────────────────

  Future<void> connect() async {
    if (_state == WsConnectionState.connected ||
        _state == WsConnectionState.connecting) {
      return;
    }

    _updateState(WsConnectionState.connecting);
    try {
      final token = await _storage.readAccessToken();
      final wsUri = Uri.parse('${AppConstants.wsUrl}?token=$token');

      _channel = WebSocketChannel.connect(wsUri);
      await _channel!.ready;

      _updateState(WsConnectionState.connected);
      _retryCount = 0;
      _startHeartbeat();
      _listenMessages();
      _resubscribeAll();
    } catch (_) {
      _scheduleReconnect();
    }
  }

  Future<void> disconnect() async {
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _stopHeartbeat();

    await _channelSub?.cancel();
    _channelSub = null;

    await _channel?.sink.close();
    _channel = null;

    _updateState(WsConnectionState.disconnected);
  }

  // ── 구독 관리 ───────────────────────────────────────────────

  void subscribe(String channel, {String? exchange, String? market}) {
    final sub = (channel: channel, exchange: exchange, market: market);
    _activeSubscriptions.add(sub);

    if (_state == WsConnectionState.connected) {
      _sendSubscribe('subscribe', channel, exchange, market);
    }
  }

  void unsubscribe(String channel, {String? exchange, String? market}) {
    _activeSubscriptions.removeWhere(
      (s) =>
          s.channel == channel &&
          s.exchange == exchange &&
          s.market == market,
    );

    if (_state == WsConnectionState.connected) {
      _sendSubscribe('unsubscribe', channel, exchange, market);
    }
  }

  // ── WidgetsBindingObserver ──────────────────────────────────

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.paused:
        disconnect();
      case AppLifecycleState.resumed:
        connect();
      default:
        break;
    }
  }

  // ── 내부 구현 ───────────────────────────────────────────────

  void _send(Map<String, dynamic> data) {
    if (_channel == null) return;
    _channel!.sink.add(jsonEncode(data));
  }

  void _sendSubscribe(
    String action,
    String channel,
    String? exchange,
    String? market,
  ) {
    final msg = <String, dynamic>{'action': action, 'channel': channel};
    if (exchange != null) msg['exchange'] = exchange;
    if (market != null) msg['market'] = market;
    _send(msg);
  }

  void _listenMessages() {
    _channelSub = _channel?.stream.listen(
      (raw) {
        try {
          final json = jsonDecode(raw as String) as Map<String, dynamic>;
          final msg = WsMessage.fromJson(json);
          _messageCtrl.add(msg);
          _dispatchMessage(msg);
        } catch (_) {
          // parse 오류는 무시
        }
      },
      onError: (_) => _scheduleReconnect(),
      onDone: () {
        if (_state != WsConnectionState.disconnected) {
          _scheduleReconnect();
        }
      },
    );
  }

  void _dispatchMessage(WsMessage msg) {
    if (msg.action == 'pong') {
      _pongTimeoutTimer?.cancel();
      _pongTimeoutTimer = null;
      return;
    }

    // 채널 데이터 메시지 라우팅
    final channelKey = msg.channel;
    if (channelKey != null && _channelCtrlMap.containsKey(channelKey)) {
      _channelCtrlMap[channelKey]!.add(msg);
    }
  }

  void _startHeartbeat() {
    _heartbeatTimer = Timer.periodic(AppConstants.wsHeartbeatInterval, (_) {
      _send({'action': 'ping'});
      _pongTimeoutTimer = Timer(AppConstants.wsPongTimeout, () {
        _scheduleReconnect();
      });
    });
  }

  void _stopHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
    _pongTimeoutTimer?.cancel();
    _pongTimeoutTimer = null;
  }

  void _scheduleReconnect() {
    if (_state == WsConnectionState.disconnected) return;
    _stopHeartbeat();
    _updateState(WsConnectionState.reconnecting);

    final delaySec =
        (1 << _retryCount).clamp(1, AppConstants.wsMaxRetryDelaySec);
    _retryCount++;

    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(Duration(seconds: delaySec), () async {
      await _channelSub?.cancel();
      _channelSub = null;
      await _channel?.sink.close();
      _channel = null;
      await connect();
    });
  }

  void _resubscribeAll() {
    for (final sub in _activeSubscriptions) {
      _sendSubscribe('subscribe', sub.channel, sub.exchange, sub.market);
    }
  }

  void _updateState(WsConnectionState newState) {
    _state = newState;
    if (!_stateCtrl.isClosed) _stateCtrl.add(newState);
  }

  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    disconnect();
    _messageCtrl.close();
    _stateCtrl.close();
    for (final ctrl in _channelCtrlMap.values) {
      ctrl.close();
    }
    _channelCtrlMap.clear();
  }
}
