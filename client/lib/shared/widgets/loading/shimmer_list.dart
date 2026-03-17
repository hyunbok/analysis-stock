import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

/// 코인 목록 스켈레톤 — CoinListTile 형태 shimmer.
class ShimmerList extends StatelessWidget {
  final int count;

  const ShimmerList({super.key, this.count = 8});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final baseColor = isDark ? const Color(0xFF2A2B35) : const Color(0xFFE0E0E0);
    final highlightColor =
        isDark ? const Color(0xFF3A3B48) : const Color(0xFFF5F5F5);

    return Shimmer.fromColors(
      baseColor: baseColor,
      highlightColor: highlightColor,
      child: ListView.separated(
        physics: const NeverScrollableScrollPhysics(),
        itemCount: count,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (_, __) => const _ShimmerCoinTile(),
      ),
    );
  }
}

class _ShimmerCoinTile extends StatelessWidget {
  const _ShimmerCoinTile();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: const BoxDecoration(
              color: Colors.white,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(width: 80, height: 14, color: Colors.white),
                const SizedBox(height: 6),
                Container(width: 50, height: 12, color: Colors.white),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Container(width: 90, height: 14, color: Colors.white),
              const SizedBox(height: 6),
              Container(width: 60, height: 12, color: Colors.white),
            ],
          ),
        ],
      ),
    );
  }
}
