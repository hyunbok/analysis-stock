import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/auth_state_provider.dart';
import '../../../core/providers/storage_provider.dart';
import '../../../core/providers/ws_provider.dart';
import '../../../core/websocket/ws_connection_state.dart';
import '../models/auth_tokens.dart';
import '../models/user.dart';
import '../repositories/auth_repository.dart';

part 'auth_provider.g.dart';

/// 현재 로그인된 사용자.
///
/// null이면 비로그인 상태.
@riverpod
User? currentUser(CurrentUserRef ref) {
  return ref.watch(authStateProvider).valueOrNull;
}

/// 로그인/로그아웃/소셜 로그인 등 인증 액션 제공자.
@riverpod
class AuthNotifier extends _$AuthNotifier {
  @override
  AsyncValue<void> build() => const AsyncData(null);

  /// 이메일 로그인
  Future<void> login({
    required String email,
    required String password,
  }) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final repo = ref.read(authRepositoryProvider);
      final tokens = await repo.login(email: email, password: password);
      await _saveAndApplyTokens(tokens);
    });
  }

  /// 소셜 로그인 (Google / Apple)
  Future<void> socialLogin({
    required String provider,
    required String idToken,
  }) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final repo = ref.read(authRepositoryProvider);
      // TODO(auth): SocialLoginRequest 사용으로 교체
      final tokens = await repo.login(email: '', password: ''); // placeholder
      await _saveAndApplyTokens(tokens);
    });
  }

  /// 로그아웃
  Future<void> logout() async {
    state = const AsyncLoading();
    try {
      await ref.read(authRepositoryProvider).logout();
    } catch (_) {
      // 서버 로그아웃 실패해도 로컬 상태는 초기화
    }
    // WS 연결 해제
    final wsState = ref.read(wsConnectionStateProvider).valueOrNull;
    if (wsState == WsConnectionState.connected) {
      await ref.read(wsClientProvider).disconnect();
    }
    await ref.read(authStateProvider.notifier).logout();
    state = const AsyncData(null);
  }

  Future<void> _saveAndApplyTokens(AuthTokens tokens) async {
    await ref.read(secureStorageProvider).saveTokens(
          accessToken: tokens.accessToken,
          refreshToken: tokens.refreshToken,
        );
    // 사용자 정보 조회
    final user = await ref.read(authRepositoryProvider).getMe();
    await ref.read(authStateProvider.notifier).setUser(user);
    // WS 연결
    await ref.read(wsClientProvider).connect();
  }
}
