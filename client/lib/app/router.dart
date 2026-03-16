import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../core/providers/auth_state_provider.dart';
import '../features/ai_trading/screens/ai_trading_screen.dart';
import '../features/auth/models/user.dart';
import '../features/auth/screens/email_verify_screen.dart';
import '../features/auth/screens/forgot_password_screen.dart';
import '../features/auth/screens/login_screen.dart';
import '../features/auth/screens/register_screen.dart';
import '../features/auth/screens/splash_screen.dart';
import '../features/exchange/screens/exchange_screen.dart';
import '../features/history/screens/history_screen.dart';
import '../features/home/screens/home_screen.dart';
import '../features/notifications/screens/notifications_screen.dart';
import '../features/portfolio/screens/portfolio_screen.dart';
import '../features/settings/screens/more_screen.dart';
import '../features/settings/screens/profile_screen.dart';
import '../features/settings/screens/settings_screen.dart';
import '../features/settings/screens/terms_screen.dart';
import '../features/trading/screens/trading_screen.dart';
import '../shared/widgets/scaffold_with_nav_bar.dart';

part 'router.g.dart';

/// GoRouter 인스턴스 프로바이더.
///
/// - [_RouterNotifier]가 authState 변화를 [refreshListenable]로 GoRouter에 전달
/// - GoRouter 인스턴스는 한 번만 생성됨 (keepAlive: true)
/// - 인증 가드: redirect에서 notifier.authState 참조
@Riverpod(keepAlive: true)
GoRouter router(RouterRef ref) {
  final notifier = _RouterNotifier(ref);
  ref.onDispose(notifier.dispose);

  return GoRouter(
    initialLocation: '/splash',
    debugLogDiagnostics: kDebugMode,
    refreshListenable: notifier,
    redirect: (context, state) {
      final authState = notifier.authState;

      // 인증 로딩 중 → /splash 유지
      if (authState.isLoading) {
        return state.matchedLocation == '/splash' ? null : '/splash';
      }

      final isAuthenticated = authState.valueOrNull != null;
      final loc = state.matchedLocation;
      final isSplash = loc == '/splash';
      final isAuthRoute = loc.startsWith('/login') ||
          loc.startsWith('/register') ||
          loc.startsWith('/forgot-password') ||
          loc.startsWith('/email-verify');

      // 스플래시: 로딩 완료 후 인증 상태에 따라 분기
      if (isSplash) return isAuthenticated ? '/home' : '/login';
      if (!isAuthenticated && !isAuthRoute) return '/login';
      if (isAuthenticated && isAuthRoute) return '/home';
      return null;
    },
    routes: [
      GoRoute(
        path: '/splash',
        builder: (_, __) => const SplashScreen(),
      ),
      GoRoute(
        path: '/login',
        builder: (_, __) => const LoginScreen(),
      ),
      GoRoute(
        path: '/register',
        builder: (_, __) => const RegisterScreen(),
      ),
      GoRoute(
        path: '/forgot-password',
        builder: (_, __) => const ForgotPasswordScreen(),
      ),
      GoRoute(
        path: '/email-verify',
        builder: (_, __) => const EmailVerifyScreen(),
      ),

      // ─── Bottom Navigation Shell ──────────────────────────────────
      StatefulShellRoute.indexedStack(
        builder: (_, __, navigationShell) =>
            ScaffoldWithNavBar(navigationShell: navigationShell),
        branches: [
          // 탭 0: 홈
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/home',
                builder: (_, __) => const HomeScreen(),
              ),
            ],
          ),

          // 탭 1: 트레이딩
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/trading',
                builder: (_, __) => const TradingScreen(),
                routes: [
                  GoRoute(
                    path: ':coinId',
                    builder: (_, state) => TradingDetailScreen(
                      coinId: state.pathParameters['coinId']!,
                    ),
                  ),
                ],
              ),
            ],
          ),

          // 탭 2: AI 매매
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/ai-trading',
                builder: (_, __) => const AiTradingScreen(),
              ),
            ],
          ),

          // 탭 3: 자산
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/portfolio',
                builder: (_, __) => const PortfolioScreen(),
              ),
            ],
          ),

          // 탭 4: 더보기
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/more',
                builder: (_, __) => const MoreScreen(),
                routes: [
                  GoRoute(
                    path: 'exchanges',
                    builder: (_, __) => const ExchangeScreen(),
                  ),
                  GoRoute(
                    path: 'history',
                    builder: (_, __) => const HistoryScreen(),
                  ),
                  GoRoute(
                    path: 'notifications',
                    builder: (_, __) => const NotificationsScreen(),
                  ),
                  GoRoute(
                    path: 'settings',
                    builder: (_, __) => const SettingsScreen(),
                  ),
                  GoRoute(
                    path: 'profile',
                    builder: (_, __) => const ProfileScreen(),
                  ),
                  GoRoute(
                    path: 'terms',
                    builder: (_, __) => const TermsScreen(),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    ],
  );
}

/// GoRouter의 [GoRouter.refreshListenable]에 연결되는 notifier.
///
/// authStateProvider 변화 시 [notifyListeners]를 호출해 GoRouter redirect를 재평가한다.
/// GoRouter 인스턴스는 유지하면서 redirect만 재실행되므로 네비게이션 스택이 리셋되지 않는다.
class _RouterNotifier extends ChangeNotifier {
  final Ref _ref;
  AsyncValue<User?> authState;

  _RouterNotifier(this._ref) {
    authState = _ref.read(authStateProvider);
    _ref.listen<AsyncValue<User?>>(authStateProvider, (_, next) {
      authState = next;
      notifyListeners();
    });
  }
}
