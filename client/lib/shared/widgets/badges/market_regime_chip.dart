import 'package:flutter/material.dart';

enum MarketRegime { trend, range, transition }

/// 장세 분류 칩.
///
/// - trend: 빨강 + "추세장"
/// - range: 회색 + "횡보장"
/// - transition: 오렌지 + "전환장"
class MarketRegimeChip extends StatelessWidget {
  final MarketRegime regime;
  final double? probability;

  const MarketRegimeChip({
    super.key,
    required this.regime,
    this.probability,
  });

  @override
  Widget build(BuildContext context) {
    final (color, label, icon) = switch (regime) {
      MarketRegime.trend => (
          const Color(0xFFF23645),
          '추세장',
          Icons.trending_up
        ),
      MarketRegime.range => (
          const Color(0xFF9E9E9E),
          '횡보장',
          Icons.trending_flat
        ),
      MarketRegime.transition => (
          const Color(0xFFFF9800),
          '전환장',
          Icons.swap_horiz
        ),
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 4),
          Text(
            label,
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: color, fontWeight: FontWeight.w600),
          ),
          if (probability != null) ...[
            const SizedBox(width: 4),
            Text(
              '${(probability! * 100).toStringAsFixed(0)}%',
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(color: color),
            ),
          ],
        ],
      ),
    );
  }
}
