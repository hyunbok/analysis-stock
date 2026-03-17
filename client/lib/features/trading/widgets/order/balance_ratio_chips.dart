import 'package:flutter/material.dart';

/// 잔고 비율 선택 칩 — 25/50/75/100%.
class BalanceRatioChips extends StatelessWidget {
  final ValueChanged<double> onRatioSelected;

  const BalanceRatioChips({super.key, required this.onRatioSelected});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [25, 50, 75, 100].map((pct) {
        return Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 3),
            child: OutlinedButton(
              onPressed: () => onRatioSelected(pct / 100.0),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 8),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              child: Text(
                '$pct%',
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}
