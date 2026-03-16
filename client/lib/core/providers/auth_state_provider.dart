import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../features/auth/models/user.dart';
import 'storage_provider.dart';

part 'auth_state_provider.g.dart';

/// 앱 전역 인증 상태의 단일 진실 공급원 (Single Source of Truth).
///
/// 상태: [AsyncValue<User?>]
/// - `AsyncData(User)` → 로그인됨
/// - `AsyncData(null)` → 로그아웃 상태
/// - `AsyncLoading()`  → 초기 토큰 확인 중
///
/// GoRouter redirect에서:
/// ```dart
/// final isAuthenticated = ref.watch(authStateProvider).valueOrNull != null;
/// ```
@Riverpod(keepAlive: true)
class AuthState extends _$AuthState {
  @override
  Future<User?> build() async {
    final storage = ref.watch(secureStorageProvider);
    final refreshToken = await storage.readRefreshToken();
    if (refreshToken == null) return null;

    // 저장된 토큰이 있으면 사용자 정보 조회 시도
    // (실제 구현은 auth feature에서 authRepository를 통해 처리)
    // TODO(auth): authRepository.getMe() 호출로 교체 (v1-24)
    return null;
  }

  /// 로그인 성공 후 User 세팅 및 WS 연결
  Future<void> setUser(User user) async {
    state = AsyncData(user);
  }

  /// 로그아웃: 토큰 삭제 + 상태 초기화 + WS 연결 해제
  Future<void> logout() async {
    try {
      await ref.read(secureStorageProvider).clearTokens();
    } catch (_) {
      // 토큰 삭제 실패(PlatformException 등)는 무시하고 상태 초기화 진행
    }
    state = const AsyncData(null);
  }

  bool get isAuthenticated => state.valueOrNull != null;
}
