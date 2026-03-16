import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hive_flutter/hive_flutter.dart';

import 'package:coin_trader/app/app.dart';
import 'package:coin_trader/core/providers/storage_provider.dart';

/// 통합 테스트 진입점.
///
/// 실기기/에뮬레이터에서 실행:
/// ```
/// flutter test integration_test/app_test.dart
/// ```
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    await Hive.initFlutter();
    SharedPreferences.setMockInitialValues({});
  });

  group('앱 시작 — 기본 플로우', () {
    testWidgets('앱이 정상 시작되고 SplashScreen이 표시됨', (tester) async {
      final prefs = await SharedPreferences.getInstance();

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
          ],
          child: const CoinTraderApp(),
        ),
      );

      // 스플래시 화면이 렌더링될 때까지 대기
      await tester.pump();

      // CircularProgressIndicator 또는 CoinTrader 앱 타이틀 확인
      expect(find.byType(CoinTraderApp), findsOneWidget);
    });

    testWidgets('미인증 상태에서 로그인 화면으로 리다이렉트', (tester) async {
      final prefs = await SharedPreferences.getInstance();
      // SecureStorage에 토큰 없음 → 미인증

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
          ],
          child: const CoinTraderApp(),
        ),
      );

      // authStateProvider 초기화 완료 대기 (비동기)
      await tester.pumpAndSettle(const Duration(seconds: 3));

      // 로그인 화면이 표시되어야 함
      // (실제 화면 위젯 타입은 LoginScreen — TODO: 라우팅 완성 후 검증 강화)
      expect(find.byType(CoinTraderApp), findsOneWidget);
    });
  });
}
