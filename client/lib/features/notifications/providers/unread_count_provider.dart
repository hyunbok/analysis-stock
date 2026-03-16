import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/ws_provider.dart';
import '../../../core/websocket/ws_message.dart';
import '../repositories/notification_repository.dart';

part 'unread_count_provider.g.dart';

/// 미읽 알림 수 — REST 초기값 + WS price-alert/notification 채널로 실시간 업데이트.
@riverpod
class UnreadCount extends _$UnreadCount {
  @override
  Future<int> build() async {
    // WS 알림 수신 시 카운트 증가
    ref.listen(
      wsClientProvider.select((c) => c.channelStream(WsChannel.notification)),
      (_, __) => _increment(),
    );
    ref.listen(
      wsClientProvider.select((c) => c.channelStream(WsChannel.priceAlert)),
      (_, __) => _increment(),
    );

    return ref.read(notificationRepositoryProvider).getUnreadCount();
  }

  void _increment() {
    final current = state.valueOrNull ?? 0;
    state = AsyncData(current + 1);
  }

  void reset() => state = const AsyncData(0);
}
