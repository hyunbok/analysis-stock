import 'package:flutter/material.dart';

/// 회원가입 화면.
/// TODO(auth): 실제 UI 구현 (v1-24)
class RegisterScreen extends StatelessWidget {
  const RegisterScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Sign Up')),
      body: const Center(child: Text('Register Screen — TODO')),
    );
  }
}
