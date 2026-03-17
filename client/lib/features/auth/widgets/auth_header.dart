import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// 인증 화면 상단 헤더 — 로고 + 앱명 + 환영 메시지.
class AuthHeader extends StatelessWidget {
  final String? subtitle;

  const AuthHeader({super.key, this.subtitle});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Column(
      children: [
        SvgPicture.asset(
          'assets/icons/logo.svg',
          width: 64,
          height: 64,
        ),
        const SizedBox(height: 16),
        Text(
          'CoinTrader',
          style: theme.textTheme.headlineMedium?.copyWith(
            fontWeight: FontWeight.w700,
          ),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 8),
          Text(
            subtitle!,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
            textAlign: TextAlign.center,
          ),
        ],
      ],
    );
  }
}
