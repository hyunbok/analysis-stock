import 'package:flutter/material.dart';

/// 확인 다이얼로그 바텀시트.
///
/// 주문 확인, AI ON/OFF 확인 등 사용자 확인이 필요한 액션에 사용.
class ConfirmBottomSheet extends StatelessWidget {
  final String title;
  final String? message;
  final Widget? content;
  final String confirmLabel;
  final String cancelLabel;
  final Color? confirmColor;
  final VoidCallback? onConfirm;

  const ConfirmBottomSheet({
    super.key,
    required this.title,
    this.message,
    this.content,
    this.confirmLabel = '확인',
    this.cancelLabel = '취소',
    this.confirmColor,
    this.onConfirm,
  });

  static Future<bool?> show(
    BuildContext context, {
    required String title,
    String? message,
    Widget? content,
    String confirmLabel = '확인',
    String cancelLabel = '취소',
    Color? confirmColor,
  }) {
    return showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => ConfirmBottomSheet(
        title: title,
        message: message,
        content: content,
        confirmLabel: confirmLabel,
        cancelLabel: cancelLabel,
        confirmColor: confirmColor,
        onConfirm: () => Navigator.pop(context, true),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          24,
          24,
          24,
          MediaQuery.of(context).viewInsets.bottom + 24,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: theme.colorScheme.onSurfaceVariant.withOpacity(0.4),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 20),
            Text(title, style: theme.textTheme.headlineSmall),
            if (message != null) ...[
              const SizedBox(height: 12),
              Text(message!, style: theme.textTheme.bodyMedium),
            ],
            if (content != null) ...[
              const SizedBox(height: 16),
              content!,
            ],
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: Text(cancelLabel),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: onConfirm,
                    style: confirmColor != null
                        ? FilledButton.styleFrom(
                            backgroundColor: confirmColor,
                          )
                        : null,
                    child: Text(confirmLabel),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
