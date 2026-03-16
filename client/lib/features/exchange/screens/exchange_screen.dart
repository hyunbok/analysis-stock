import 'package:flutter/material.dart';

/// 거래소 설정 화면 — API 키 등록/관리/연결 테스트.
/// TODO(exchange): 실제 UI 구현
class ExchangeScreen extends StatelessWidget {
  const ExchangeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Exchange Settings')),
      body: const Center(child: Text('Exchange Settings — TODO')),
    );
  }
}
