import 'package:flutter/material.dart';

/// 매매 내역 화면 — 주문/체결 내역, 기간 필터, 요약 통계.
/// TODO(history): 실제 UI 구현
class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Trade History')),
      body: const Center(child: Text('History — TODO')),
    );
  }
}
