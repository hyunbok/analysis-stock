import 'package:flutter/material.dart';

import '../../../core/utils/format_utils.dart';
import '../models/exchange_account.dart';

/// 연결된 거래소 계정 카드.
class ExchangeAccountCard extends StatelessWidget {
  final ExchangeAccount account;
  final VoidCallback? onEdit;
  final VoidCallback? onDelete;

  const ExchangeAccountCard({
    super.key,
    required this.account,
    this.onEdit,
    this.onDelete,
  });

  String get _exchangeLabel => switch (account.exchange.toLowerCase()) {
        'upbit' => '업비트',
        'coinone' => '코인원',
        _ => account.exchange,
      };

  IconData get _exchangeIcon => switch (account.exchange.toLowerCase()) {
        'upbit' => Icons.currency_bitcoin,
        'coinone' => Icons.monetization_on_outlined,
        _ => Icons.account_balance,
      };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(_exchangeIcon, size: 24),
                const SizedBox(width: 8),
                Text(
                  _exchangeLabel,
                  style: theme.textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const Spacer(),
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: account.isConnected
                        ? const Color(0xFF4CAF50)
                        : const Color(0xFF9E9E9E),
                  ),
                ),
                const SizedBox(width: 6),
                Text(
                  account.isConnected ? '연결됨' : '미연결',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: account.isConnected
                        ? const Color(0xFF4CAF50)
                        : theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              account.label,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            if (account.lastVerified != null) ...[
              const SizedBox(height: 4),
              Text(
                '마지막 검증: ${FormatUtils.formatDate(account.lastVerified!)}',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
            const SizedBox(height: 12),
            Row(
              children: [
                if (onEdit != null)
                  TextButton.icon(
                    onPressed: onEdit,
                    icon: const Icon(Icons.edit, size: 16),
                    label: const Text('수정'),
                  ),
                if (onDelete != null)
                  TextButton.icon(
                    onPressed: onDelete,
                    icon: const Icon(Icons.delete_outline, size: 16),
                    label: const Text('삭제'),
                    style: TextButton.styleFrom(
                      foregroundColor: Theme.of(context).colorScheme.error,
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
