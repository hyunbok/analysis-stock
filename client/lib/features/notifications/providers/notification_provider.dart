import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../models/notification.dart';
import '../repositories/notification_repository.dart';

part 'notification_provider.g.dart';

@riverpod
class NotificationList extends _$NotificationList {
  @override
  Future<List<AppNotification>> build() {
    return ref.watch(notificationRepositoryProvider).getNotifications();
  }

  Future<void> markRead(String id) async {
    await ref.read(notificationRepositoryProvider).markRead(id);
    ref.invalidateSelf();
  }

  Future<void> markAllRead() async {
    await ref.read(notificationRepositoryProvider).markAllRead();
    ref.invalidateSelf();
  }

  Future<void> delete(String id) async {
    await ref.read(notificationRepositoryProvider).deleteNotification(id);
    ref.invalidateSelf();
  }
}
