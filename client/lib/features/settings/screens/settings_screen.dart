import 'package:flutter/material.dart';

/// 설정 화면 — 언어, 테마, 가격 색상, 알림 설정.
/// TODO(settings): 실제 UI 구현
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: const Center(child: Text('Settings — TODO')),
    );
  }
}
