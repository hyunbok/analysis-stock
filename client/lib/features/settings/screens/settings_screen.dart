import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers/settings_provider.dart';

/// 설정 화면 — 언어, 테마, 가격 색상, 알림 설정.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsNotifierProvider);
    final notifier = ref.read(settingsNotifierProvider.notifier);

    return Scaffold(
      appBar: AppBar(title: const Text('설정')),
      body: ListView(
        children: [
          // 앱 설정
          _SettingsSection(
            title: '앱 설정',
            children: [
              // 테마
              ListTile(
                leading: const Icon(Icons.brightness_6_outlined),
                title: const Text('테마'),
                trailing: _ThemeModeSelector(
                  current: settings.themeMode,
                  onChanged: notifier.setThemeMode,
                ),
              ),
              const Divider(indent: 56, height: 1),
              // 언어
              ListTile(
                leading: const Icon(Icons.language_outlined),
                title: const Text('언어'),
                trailing: _LocaleSelector(
                  current: settings.locale,
                  onChanged: notifier.setLocale,
                ),
              ),
              const Divider(indent: 56, height: 1),
              // 가격 색상
              ListTile(
                leading: const Icon(Icons.palette_outlined),
                title: const Text('가격 색상'),
                subtitle: Text(
                  settings.priceColorScheme == 'korean' ? '한국식 (상승 빨강)' : '글로벌 (상승 초록)',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
                trailing: _PriceColorSelector(
                  current: settings.priceColorScheme,
                  onChanged: notifier.setPriceColorScheme,
                ),
              ),
            ],
          ),
          // 알림 설정
          _SettingsSection(
            title: '알림 설정',
            children: [
              SwitchListTile(
                secondary: const Icon(Icons.notifications_outlined),
                title: const Text('가격 알림'),
                value: settings.priceNotifEnabled,
                onChanged: notifier.setPriceNotifEnabled,
              ),
              const Divider(indent: 56, height: 1),
              SwitchListTile(
                secondary: const Icon(Icons.smart_toy_outlined),
                title: const Text('AI 매매 알림'),
                value: settings.aiNotifEnabled,
                onChanged: notifier.setAiNotifEnabled,
              ),
              const Divider(indent: 56, height: 1),
              SwitchListTile(
                secondary: const Icon(Icons.receipt_long_outlined),
                title: const Text('체결 알림'),
                value: settings.tradeNotifEnabled,
                onChanged: notifier.setTradeNotifEnabled,
              ),
            ],
          ),
          // 보안
          _SettingsSection(
            title: '보안',
            children: [
              ListTile(
                leading: const Icon(Icons.lock_outline),
                title: const Text('비밀번호 변경'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => context.go('/more/profile'),
              ),
              const Divider(indent: 56, height: 1),
              SwitchListTile(
                secondary: const Icon(Icons.fingerprint),
                title: const Text('생체 인증'),
                subtitle: const Text('지문/Face ID로 로그인'),
                value: false,
                onChanged: (v) {
                  // TODO(security): 생체 인증 설정 연동
                },
              ),
            ],
          ),
          // 정보
          _SettingsSection(
            title: '정보',
            children: [
              ListTile(
                leading: const Icon(Icons.info_outline),
                title: const Text('버전'),
                trailing: const Text(
                  '1.0.0',
                  style: TextStyle(color: Colors.grey),
                ),
              ),
              const Divider(indent: 56, height: 1),
              ListTile(
                leading: const Icon(Icons.privacy_tip_outlined),
                title: const Text('개인정보 처리방침'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () {},
              ),
            ],
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

class _SettingsSection extends StatelessWidget {
  final String title;
  final List<Widget> children;

  const _SettingsSection({required this.title, required this.children});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 8),
          child: Text(
            title,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: Theme.of(context).colorScheme.primary,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 0.5,
                ),
          ),
        ),
        Card(
          margin: const EdgeInsets.symmetric(horizontal: 16),
          child: Column(children: children),
        ),
      ],
    );
  }
}

class _ThemeModeSelector extends StatelessWidget {
  final ThemeMode current;
  final ValueChanged<ThemeMode> onChanged;

  const _ThemeModeSelector({required this.current, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return DropdownButton<ThemeMode>(
      value: current,
      underline: const SizedBox.shrink(),
      onChanged: (v) => v != null ? onChanged(v) : null,
      items: const [
        DropdownMenuItem(value: ThemeMode.system, child: Text('시스템')),
        DropdownMenuItem(value: ThemeMode.dark, child: Text('다크')),
        DropdownMenuItem(value: ThemeMode.light, child: Text('라이트')),
      ],
    );
  }
}

class _LocaleSelector extends StatelessWidget {
  final String current;
  final ValueChanged<String> onChanged;

  const _LocaleSelector({required this.current, required this.onChanged});

  static const _locales = {
    'ko': '한국어',
    'en': 'English',
    'ja': '日本語',
    'zh': '中文',
    'es': 'Español',
  };

  @override
  Widget build(BuildContext context) {
    return DropdownButton<String>(
      value: current,
      underline: const SizedBox.shrink(),
      onChanged: (v) => v != null ? onChanged(v) : null,
      items: _locales.entries
          .map(
            (e) => DropdownMenuItem(value: e.key, child: Text(e.value)),
          )
          .toList(),
    );
  }
}

class _PriceColorSelector extends StatelessWidget {
  final String current;
  final ValueChanged<String> onChanged;

  const _PriceColorSelector({required this.current, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return DropdownButton<String>(
      value: current,
      underline: const SizedBox.shrink(),
      onChanged: (v) => v != null ? onChanged(v) : null,
      items: const [
        DropdownMenuItem(value: 'korean', child: Text('한국식')),
        DropdownMenuItem(value: 'global', child: Text('글로벌')),
      ],
    );
  }
}
