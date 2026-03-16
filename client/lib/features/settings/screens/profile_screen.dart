import 'package:flutter/material.dart';

/// 프로필 수정 화면 — 닉네임 변경, 아바타 업로드, 계정 삭제.
/// TODO(settings): 실제 UI 구현
class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Profile')),
      body: const Center(child: Text('Profile — TODO')),
    );
  }
}
