import 'package:flutter/material.dart';

/// 에러 상태 표시 위젯 — 아이콘 + 메시지 + 재시도 버튼.
class ErrorView extends StatelessWidget {
  final Object? error;
  final VoidCallback? onRetry;
  final String? message;

  const ErrorView({
    super.key,
    this.error,
    this.onRetry,
    this.message,
  });

  @override
  Widget build(BuildContext context) {
    final displayMessage = message ?? error?.toString() ?? '오류가 발생했습니다';

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.error_outline,
              size: 64,
              color: Theme.of(context).colorScheme.error,
            ),
            const SizedBox(height: 16),
            Text(
              displayMessage,
              style: Theme.of(context).textTheme.bodyMedium,
              textAlign: TextAlign.center,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: 24),
              FilledButton.tonal(
                onPressed: onRetry,
                child: const Text('다시 시도'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
