import 'package:flutter/material.dart';

/// 로그인 화면 — 이메일 인증 + 소셜 로그인 (Google/Apple).
/// TODO(auth): 실제 UI 구현 (v1-24)
class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Login')),
      body: const Center(child: Text('Login Screen — TODO')),
    );
  }
}
