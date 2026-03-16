import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/dio_provider.dart';
import '../models/notification.dart';

part 'notification_repository.g.dart';

@riverpod
NotificationRepository notificationRepository(
    NotificationRepositoryRef ref) {
  return NotificationRepository(ref.watch(dioClientProvider));
}

class NotificationRepository {
  final Dio _dio;

  const NotificationRepository(this._dio);

  Future<List<AppNotification>> getNotifications() async {
    final res =
        await _dio.get<Map<String, dynamic>>('/api/v1/notifications');
    final items = res.data!['data']['items'] as List<dynamic>;
    return items
        .map((e) => AppNotification.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> markRead(String id) async {
    await _dio.patch<void>('/api/v1/notifications/$id/read');
  }

  Future<void> markAllRead() async {
    await _dio.post<void>('/api/v1/notifications/mark-all-read');
  }

  Future<void> deleteNotification(String id) async {
    await _dio.delete<void>('/api/v1/notifications/$id');
  }

  Future<int> getUnreadCount() async {
    final res = await _dio
        .get<Map<String, dynamic>>('/api/v1/notifications/unread-count');
    return res.data!['data']['count'] as int;
  }
}
