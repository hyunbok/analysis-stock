import 'package:flutter/material.dart';

/// 비밀번호 찾기 화면.
/// TODO(auth): 실제 UI 구현 (v1-24)
class ForgotPasswordScreen extends StatelessWidget {
  const ForgotPasswordScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Forgot Password')),
      body: const Center(child: Text('Forgot Password Screen — TODO')),
    );
  }
}
