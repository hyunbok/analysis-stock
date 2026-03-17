import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../app/theme.dart';
import '../../../../core/utils/format_utils.dart';
import '../../../../shared/widgets/confirm_bottom_sheet.dart';
import '../../../../shared/widgets/order_button.dart';
import '../../../../shared/widgets/badges/order_side_badge.dart' as badge;
import '../../../home/models/coin.dart';
import '../../providers/order_form_provider.dart';
import '../../providers/order_provider.dart';
import 'balance_ratio_chips.dart';

/// 주문 폼 전체 위젯.
class OrderForm extends ConsumerStatefulWidget {
  final Coin coin;

  const OrderForm({super.key, required this.coin});

  @override
  ConsumerState<OrderForm> createState() => _OrderFormState();
}

class _OrderFormState extends ConsumerState<OrderForm> {
  final _priceController = TextEditingController();
  final _quantityController = TextEditingController();

  @override
  void dispose() {
    _priceController.dispose();
    _quantityController.dispose();
    super.dispose();
  }

  void _syncPriceController(String formPrice) {
    if (_priceController.text != formPrice) {
      _priceController.text = formPrice;
      _priceController.selection = TextSelection.fromPosition(
        TextPosition(offset: formPrice.length),
      );
    }
  }

  Future<void> _placeOrder(BuildContext context, WidgetRef ref) async {
    final form = ref.read(orderFormProvider);
    final price = double.tryParse(form.price.replaceAll(',', '')) ?? 0;
    final quantity = double.tryParse(form.quantity) ?? 0;

    if (price <= 0 || quantity <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('가격과 수량을 올바르게 입력해주세요')),
      );
      return;
    }

    final confirmed = await ConfirmBottomSheet.show(
      context,
      title: '주문 확인',
      content: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          _OrderConfirmRow(
            label: '종류',
            value: form.side == OrderSide.buy ? '매수' : '매도',
          ),
          _OrderConfirmRow(label: '가격', value: '${FormatUtils.formatKrw(price)}원'),
          _OrderConfirmRow(label: '수량', value: FormatUtils.formatCoinAmount(quantity)),
          _OrderConfirmRow(
            label: '총액',
            value: '${FormatUtils.formatKrw(price * quantity)}원',
          ),
        ],
      ),
      confirmLabel: form.side == OrderSide.buy ? '매수 주문' : '매도 주문',
      confirmColor: form.side == OrderSide.buy
          ? Theme.of(context).extension<TradingColors>()!.buyColor
          : Theme.of(context).extension<TradingColors>()!.sellColor,
    );

    if (confirmed != true || !context.mounted) return;

    await ref.read(orderNotifierProvider.notifier).createOrder(
          exchangeAccountId: '',
          market: widget.coin.market,
          side: form.side == OrderSide.buy ? 'buy' : 'sell',
          type: form.type == OrderType.limit ? 'limit' : 'market',
          price: price,
          amount: quantity,
        );

    if (!context.mounted) return;
    final orderState = ref.read(orderNotifierProvider);
    if (orderState.hasError) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('주문 실패: ${orderState.error}')),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('주문이 접수되었습니다')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final form = ref.watch(orderFormProvider);
    final formNotifier = ref.read(orderFormProvider.notifier);
    final isLoading = ref.watch(orderNotifierProvider).isLoading;
    final colors = Theme.of(context).extension<TradingColors>()!;

    // 폼 가격이 외부에서 변경되면 컨트롤러 동기화
    _syncPriceController(form.price);

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // 매수/매도 탭
          SegmentedButton<OrderSide>(
            segments: const [
              ButtonSegment(value: OrderSide.buy, label: Text('매수')),
              ButtonSegment(value: OrderSide.sell, label: Text('매도')),
            ],
            selected: {form.side},
            onSelectionChanged: (v) => formNotifier.setSide(v.first),
            style: ButtonStyle(
              backgroundColor: WidgetStateProperty.resolveWith((states) {
                if (states.contains(WidgetState.selected)) {
                  return form.side == OrderSide.buy
                      ? colors.buyColor
                      : colors.sellColor;
                }
                return null;
              }),
            ),
          ),
          const SizedBox(height: 16),
          // 주문 유형
          DropdownButtonFormField<OrderType>(
            value: form.type,
            decoration: const InputDecoration(
              labelText: '주문 유형',
              border: OutlineInputBorder(),
              contentPadding:
                  EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            ),
            items: const [
              DropdownMenuItem(
                  value: OrderType.limit, child: Text('지정가')),
              DropdownMenuItem(
                  value: OrderType.market, child: Text('시장가')),
            ],
            onChanged: (v) {
              if (v != null) formNotifier.setType(v);
            },
          ),
          const SizedBox(height: 12),
          // 가격 입력 (지정가만)
          if (form.type == OrderType.limit)
            TextFormField(
              controller: _priceController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: '가격',
                suffixText: '원',
                border: OutlineInputBorder(),
                contentPadding:
                    EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              ),
              onChanged: formNotifier.setPrice,
            ),
          if (form.type == OrderType.limit) const SizedBox(height: 12),
          // 수량 입력
          TextFormField(
            controller: _quantityController,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              labelText: '수량',
              suffixText: widget.coin.symbol,
              border: const OutlineInputBorder(),
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            ),
            onChanged: formNotifier.setQuantity,
          ),
          const SizedBox(height: 8),
          // 잔고 비율
          BalanceRatioChips(
            onRatioSelected: (ratio) {
              // TODO: 실제 잔고 기반 수량 계산
              final mockBalance = 1000000.0;
              final price =
                  double.tryParse(form.price.replaceAll(',', '')) ??
                      (widget.coin.price ?? 0);
              if (price > 0) {
                final qty = (mockBalance * ratio / price);
                final qtyStr = FormatUtils.formatCoinAmount(qty);
                _quantityController.text = qtyStr;
                formNotifier.setQuantity(qtyStr);
              }
            },
          ),
          const SizedBox(height: 16),
          // 주문 정보
          _OrderInfoRow(
            label: '주문 총액',
            value: () {
              final price = double.tryParse(
                      form.price.replaceAll(',', '')) ??
                  (widget.coin.price ?? 0);
              final qty = double.tryParse(form.quantity) ?? 0;
              return '${FormatUtils.formatKrw(price * qty)}원';
            }(),
          ),
          const SizedBox(height: 4),
          const _OrderInfoRow(label: '사용 가능', value: '1,000,000 원'),
          const Spacer(),
          OrderButton(
            side: form.side == OrderSide.buy
                ? badge.OrderSide.buy
                : badge.OrderSide.sell,
            label: form.side == OrderSide.buy
                ? '${widget.coin.symbol} 매수 주문'
                : '${widget.coin.symbol} 매도 주문',
            isLoading: isLoading,
            onPressed: () => _placeOrder(context, ref),
          ),
        ],
      ),
    );
  }
}

class _OrderConfirmRow extends StatelessWidget {
  final String label;
  final String value;

  const _OrderConfirmRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  )),
          Text(value, style: Theme.of(context).textTheme.bodyMedium),
        ],
      ),
    );
  }
}

class _OrderInfoRow extends StatelessWidget {
  final String label;
  final String value;

  const _OrderInfoRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                )),
        Text(
          value,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                fontFamily: 'Inter',
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
        ),
      ],
    );
  }
}
