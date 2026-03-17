import 'package:flutter/material.dart';

/// Google / Apple 소셜 로그인 버튼.
class SocialLoginButtons extends StatelessWidget {
  final VoidCallback? onGoogleTap;
  final VoidCallback? onAppleTap;

  const SocialLoginButtons({
    super.key,
    this.onGoogleTap,
    this.onAppleTap,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        OutlinedButton.icon(
          onPressed: onGoogleTap,
          icon: const Icon(Icons.g_mobiledata, size: 24),
          label: const Text('Google로 계속하기'),
          style: OutlinedButton.styleFrom(
            minimumSize: const Size.fromHeight(48),
          ),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: onAppleTap,
          icon: const Icon(Icons.apple, size: 24),
          label: const Text('Apple로 계속하기'),
          style: OutlinedButton.styleFrom(
            minimumSize: const Size.fromHeight(48),
          ),
        ),
      ],
    );
  }
}
