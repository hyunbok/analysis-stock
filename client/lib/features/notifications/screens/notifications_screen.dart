import 'package:flutter/material.dart';

/// 알림 화면 — 알림 목록, 읽음/삭제, 미읽 뱃지.
/// TODO(notifications): 실제 UI 구현
class NotificationsScreen extends StatelessWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Notifications')),
      body: const Center(child: Text('Notifications — TODO')),
    );
  }
}
