import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/auth_state_provider.dart';
import '../../auth/models/user.dart';
import '../../auth/repositories/auth_repository.dart';

part 'profile_edit_provider.g.dart';

/// 프로필 수정 폼 상태.
class ProfileEditState {
  final String nickname;
  final bool isLoading;
  final String? error;
  final bool saved;

  const ProfileEditState({
    this.nickname = '',
    this.isLoading = false,
    this.error,
    this.saved = false,
  });

  ProfileEditState copyWith({
    String? nickname,
    bool? isLoading,
    String? error,
    bool? saved,
  }) {
    return ProfileEditState(
      nickname: nickname ?? this.nickname,
      isLoading: isLoading ?? this.isLoading,
      error: error,
      saved: saved ?? this.saved,
    );
  }
}

@riverpod
class ProfileEditNotifier extends _$ProfileEditNotifier {
  @override
  ProfileEditState build() {
    final user = ref.watch(authStateProvider).valueOrNull;
    return ProfileEditState(nickname: user?.nickname ?? '');
  }

  void setNickname(String value) {
    state = state.copyWith(nickname: value, saved: false);
  }

  Future<void> save() async {
    if (state.nickname.trim().isEmpty) return;
    state = state.copyWith(isLoading: true, error: null, saved: false);
    try {
      final user = await ref.read(authRepositoryProvider).updateMe(
            nickname: state.nickname.trim(),
          );
      await ref.read(authStateProvider.notifier).setUser(user);
      state = state.copyWith(isLoading: false, saved: true);
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    // TODO(profile): 비밀번호 변경 API 연동
    state = state.copyWith(isLoading: true, error: null);
    await Future.delayed(const Duration(milliseconds: 500));
    state = state.copyWith(isLoading: false);
  }
}
