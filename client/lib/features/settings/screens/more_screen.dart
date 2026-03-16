import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// 더보기 탭 — 거래소, 매매 내역, 알림, 설정, 프로필 메뉴.
/// TODO(more): 실제 UI 구현 (v1-28+)
class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('More')),
      body: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.swap_horiz_outlined),
            title: const Text('Exchange Settings'),
            onTap: () => context.go('/more/exchanges'),
          ),
          ListTile(
            leading: const Icon(Icons.history_outlined),
            title: const Text('Trade History'),
            onTap: () => context.go('/more/history'),
          ),
          ListTile(
            leading: const Icon(Icons.notifications_outlined),
            title: const Text('Notifications'),
            onTap: () => context.go('/more/notifications'),
          ),
          ListTile(
            leading: const Icon(Icons.settings_outlined),
            title: const Text('Settings'),
            onTap: () => context.go('/more/settings'),
          ),
          ListTile(
            leading: const Icon(Icons.person_outline),
            title: const Text('Profile'),
            onTap: () => context.go('/more/profile'),
          ),
          ListTile(
            leading: const Icon(Icons.article_outlined),
            title: const Text('Terms of Service'),
            onTap: () => context.go('/more/terms'),
          ),
        ],
      ),
    );
  }
}
