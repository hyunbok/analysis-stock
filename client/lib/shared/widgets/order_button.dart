import 'package:flutter/material.dart';

import '../../app/theme.dart';
import 'badges/order_side_badge.dart';

/// 매수/매도 주문 버튼 — 전체 너비, 색상 자동 적용.
class OrderButton extends StatelessWidget {
  final OrderSide side;
  final String label;
  final VoidCallback? onPressed;
  final bool isLoading;

  const OrderButton({
    super.key,
    required this.side,
    required this.label,
    this.onPressed,
    this.isLoading = false,
  });

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<TradingColors>()!;
    final color = side == OrderSide.buy ? colors.buyColor : colors.sellColor;

    return SizedBox(
      width: double.infinity,
      height: 52,
      child: FilledButton(
        onPressed: isLoading ? null : onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: color,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        child: isLoading
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  color: Colors.white,
                  strokeWidth: 2,
                ),
              )
            : Text(
                label,
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 16,
                ),
              ),
      ),
    );
  }
}
