import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/providers/auth_state_provider.dart';
import '../../auth/providers/auth_provider.dart';
import '../../../shared/widgets/confirm_bottom_sheet.dart';

/// 더보기 탭 — 프로필, 거래소, 매매 내역, 알림, 설정 메뉴.
class MoreScreen extends ConsumerWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authStateProvider).valueOrNull;

    return Scaffold(
      appBar: AppBar(title: const Text('더보기')),
      body: ListView(
        children: [
          // 프로필 헤더
          if (user != null) ...[
            ListTile(
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              leading: CircleAvatar(
                radius: 28,
                backgroundColor:
                    Theme.of(context).colorScheme.primaryContainer,
                child: Text(
                  user.nickname.isNotEmpty
                      ? user.nickname[0].toUpperCase()
                      : '?',
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 20,
                    color: Theme.of(context).colorScheme.onPrimaryContainer,
                  ),
                ),
              ),
              title: Text(
                user.nickname,
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.w600),
              ),
              subtitle: Text(
                user.email,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.go('/more/profile'),
            ),
            const Divider(height: 1),
          ],

          // 거래소 설정
          ListTile(
            leading: const Icon(Icons.swap_horiz_outlined),
            title: const Text('거래소 설정'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.go('/more/exchanges'),
          ),
          const Divider(indent: 56, height: 1),
          // 매매 내역
          ListTile(
            leading: const Icon(Icons.history_outlined),
            title: const Text('매매 내역'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.go('/more/history'),
          ),
          const Divider(indent: 56, height: 1),
          // 알림
          ListTile(
            leading: const Icon(Icons.notifications_outlined),
            title: const Text('알림'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.go('/more/notifications'),
          ),
          const Divider(indent: 56, height: 1),
          // 설정
          ListTile(
            leading: const Icon(Icons.settings_outlined),
            title: const Text('설정'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.go('/more/settings'),
          ),
          const Divider(indent: 56, height: 1),
          // AI 매매 설정
          ListTile(
            leading: const Icon(Icons.smart_toy_outlined),
            title: const Text('AI 매매 설정'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.go('/ai-trading'),
          ),
          const Divider(indent: 56, height: 1),
          // 이용약관
          ListTile(
            leading: const Icon(Icons.article_outlined),
            title: const Text('이용약관'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.go('/more/terms'),
          ),
          const Divider(height: 1),

          const SizedBox(height: 24),

          // 로그아웃
          ListTile(
            leading: Icon(
              Icons.logout,
              color: Theme.of(context).colorScheme.error,
            ),
            title: Text(
              '로그아웃',
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
            onTap: () => _confirmLogout(context, ref),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmLogout(BuildContext context, WidgetRef ref) async {
    final confirmed = await ConfirmBottomSheet.show(
      context,
      title: '로그아웃',
      message: '로그아웃 하시겠습니까?',
      confirmLabel: '로그아웃',
      confirmColor: Theme.of(context).colorScheme.error,
    );
    if (confirmed == true) {
      await ref.read(authNotifierProvider.notifier).logout();
    }
  }
}
