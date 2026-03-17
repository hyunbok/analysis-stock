import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers/ws_provider.dart';
import '../../../core/websocket/ws_connection_state.dart';

/// WebSocket 연결 상태 배너 — 연결 끊김/재연결 중 시 표시.
class WsConnectionBanner extends ConsumerWidget {
  const WsConnectionBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final wsState =
        ref.watch(wsConnectionStateProvider).valueOrNull ?? WsConnectionState.disconnected;

    if (wsState == WsConnectionState.connected) return const SizedBox.shrink();

    final (color, label, showSpinner) = switch (wsState) {
      WsConnectionState.connecting => (
          const Color(0xFFFFC107),
          '연결 중...',
          true
        ),
      WsConnectionState.reconnecting => (
          const Color(0xFFFFC107),
          '재연결 중...',
          true
        ),
      WsConnectionState.disconnected => (
          const Color(0xFFEF5350),
          '연결 끊김',
          false
        ),
      _ => (const Color(0xFFFFC107), '연결 중...', true),
    };

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      color: color.withOpacity(0.15),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          if (showSpinner) ...[
            SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: color,
              ),
            ),
            const SizedBox(width: 8),
          ],
          Icon(Icons.wifi_off, size: 14, color: color),
          const SizedBox(width: 6),
          Text(
            label,
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: color, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

/// AppBar actions에 사용하는 소형 WS 연결 상태 인디케이터.
class WsConnectionIndicator extends ConsumerWidget {
  const WsConnectionIndicator({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final wsState =
        ref.watch(wsConnectionStateProvider).valueOrNull ?? WsConnectionState.disconnected;

    final color = switch (wsState) {
      WsConnectionState.connected => const Color(0xFF4CAF50),
      WsConnectionState.connecting || WsConnectionState.reconnecting =>
        const Color(0xFFFFC107),
      WsConnectionState.disconnected => const Color(0xFFEF5350),
    };

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: color,
        ),
      ),
    );
  }
}
