import 'package:flutter/material.dart';

/// 거래소 선택 칩.
class ExchangeChip extends StatelessWidget {
  final String exchange;
  final bool isSelected;
  final VoidCallback? onTap;

  const ExchangeChip({
    super.key,
    required this.exchange,
    this.isSelected = false,
    this.onTap,
  });

  String get _label => switch (exchange.toLowerCase()) {
        'upbit' => '업비트',
        'coinone' => '코인원',
        'binance' => 'Binance',
        _ => exchange,
      };

  @override
  Widget build(BuildContext context) {
    return FilterChip(
      label: Text(_label),
      selected: isSelected,
      onSelected: onTap != null ? (_) => onTap!() : null,
      showCheckmark: false,
    );
  }
}
