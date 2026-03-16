import 'package:flutter/material.dart';

/// 트레이딩 화면 — TradingView 차트 + 호가창 + 주문 (탭 방식).
/// TODO(trading): 실제 UI 구현
class TradingScreen extends StatelessWidget {
  const TradingScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(child: Text('Trading — TODO')),
    );
  }
}

/// 코인 상세 트레이딩 화면.
class TradingDetailScreen extends StatelessWidget {
  final String coinId;

  const TradingDetailScreen({super.key, required this.coinId});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(coinId)),
      body: const Center(child: Text('Trading Detail — TODO')),
    );
  }
}
