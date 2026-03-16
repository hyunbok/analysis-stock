import 'package:flutter/material.dart';

/// 스플래시 화면 — 토큰 확인 후 /home 또는 /login으로 리다이렉트.
///
/// 실제 리다이렉트 로직은 GoRouter redirect에서 처리된다.
/// TODO(routing): authStateProvider 로딩 완료 후 GoRouter redirect 트리거
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: CircularProgressIndicator(),
      ),
    );
  }
}
