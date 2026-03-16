import 'package:flutter/material.dart';

/// 이메일 인증 화면.
/// TODO(auth): 실제 UI 구현 (v1-24)
class EmailVerifyScreen extends StatelessWidget {
  const EmailVerifyScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Verify Email')),
      body: const Center(child: Text('Email Verify Screen — TODO')),
    );
  }
}
