import 'package:flutter/material.dart';

/// 시간봉 선택 칩 행.
class TimeframeChips extends StatelessWidget {
  final String selectedInterval;
  final ValueChanged<String> onChanged;

  static const _timeframes = [
    ('1m', '1분'),
    ('5m', '5분'),
    ('15m', '15분'),
    ('30m', '30분'),
    ('1h', '1시'),
    ('4h', '4시'),
    ('1d', '일'),
    ('1w', '주'),
  ];

  const TimeframeChips({
    super.key,
    required this.selectedInterval,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      child: Row(
        children: _timeframes.map((tf) {
          final isSelected = selectedInterval == tf.$1;
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: FilterChip(
              label: Text(tf.$2),
              selected: isSelected,
              onSelected: (_) => onChanged(tf.$1),
              showCheckmark: false,
              padding: const EdgeInsets.symmetric(horizontal: 4),
              labelPadding: EdgeInsets.zero,
            ),
          );
        }).toList(),
      ),
    );
  }
}
