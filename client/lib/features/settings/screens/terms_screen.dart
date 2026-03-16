import 'package:flutter/material.dart';

/// 이용약관 화면 — WebView로 표시.
/// TODO(terms): WebView 연동 (v1-28+)
class TermsScreen extends StatelessWidget {
  const TermsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Terms of Service')),
      body: const Center(child: Text('Terms of Service — TODO')),
    );
  }
}
