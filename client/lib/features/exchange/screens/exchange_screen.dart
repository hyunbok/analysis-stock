import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../shared/widgets/confirm_bottom_sheet.dart';
import '../../../shared/widgets/states/empty_view.dart';
import '../../../shared/widgets/states/error_view.dart';
import '../providers/exchange_provider.dart';
import '../widgets/add_exchange_bottom_sheet.dart';
import '../widgets/exchange_account_card.dart';

/// 거래소 설정 화면 — API 키 등록/관리/연결 테스트.
class ExchangeScreen extends ConsumerWidget {
  const ExchangeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final exchangesAsync = ref.watch(exchangeListProvider);

    return Scaffold(
      appBar: AppBar(
        leading: const BackButton(),
        title: const Text('거래소 설정'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('연결된 거래소',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            exchangesAsync.when(
              loading: () =>
                  const Center(child: CircularProgressIndicator()),
              error: (e, _) => ErrorView(
                error: e,
                onRetry: () => ref.invalidate(exchangeListProvider),
              ),
              data: (exchanges) {
                if (exchanges.isEmpty) {
                  return const EmptyView(
                    icon: Icons.account_balance_outlined,
                    message: '연결된 거래소가 없습니다',
                  );
                }
                return Column(
                  children: exchanges
                      .map((account) => ExchangeAccountCard(
                            account: account,
                            onEdit: () =>
                                AddExchangeBottomSheet.show(context),
                            onDelete: () async {
                              final confirmed =
                                  await ConfirmBottomSheet.show(
                                context,
                                title: '거래소 삭제',
                                message: '이 거래소 연결을 삭제하시겠습니까?',
                                confirmLabel: '삭제',
                                confirmColor:
                                    Theme.of(context).colorScheme.error,
                              );
                              if (confirmed == true) {
                                await ref
                                    .read(exchangeListProvider.notifier)
                                    .delete(account.id);
                              }
                            },
                          ))
                      .toList(),
                );
              },
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: () => AddExchangeBottomSheet.show(context),
              icon: const Icon(Icons.add),
              label: const Text('거래소 추가'),
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
            ),
            const SizedBox(height: 24),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    const Icon(Icons.lock_outline, size: 20),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'API 키는 AES-256-GCM 방식으로 암호화 저장됩니다',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
