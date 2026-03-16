# v1-23 Flutter 프로젝트 기본 구조 및 상태 관리 설정 — 설계서

> **작성**: project-architect (아키텍처/라우팅/테마/i18n), code-architect (Riverpod/Dio/WS/저장소/features)
> **대상 태스크**: v1-23 — 클라이언트 (Flutter) 프로젝트 기본 구조 및 상태 관리 설정
> **현재 상태**: 설계 완료

---

## 1. 개요

기존 Flutter 프로젝트 골격(v1-1에서 생성)을 기반으로, 실제 기능 개발에 필요한 핵심 인프라를 구축한다:
- Riverpod 상태 관리 아키텍처
- Dio HTTP 클라이언트 (인터셉터, 토큰 갱신)
- GoRouter 라우팅 (인증 가드, Bottom Navigation)
- Material 3 테마 (Light/Dark, TradingColors)
- WebSocket 클라이언트 (서버 WS Hub 연동)
- 로컬 저장소 계층 (SecureStorage, Hive, SharedPreferences)
- i18n 다국어 (ko, en, ja, zh, es)
- Feature-first 디렉토리 구조 스캐폴딩

**의존성**: v1-1 (프로젝트 인프라), 서버 v1-5 (JWT 인증), v1-12 (WS Hub)

---

## 2. 기존 코드 현황 분석

### 2.1 현재 프로젝트 상태

| 항목 | 상태 | 비고 |
|------|------|------|
| pubspec.yaml | 완료 | flutter_riverpod, dio, go_router, hive, flutter_secure_storage 등 선언됨 |
| main.dart | 골격 | ProviderScope + MaterialApp (GoRouter 미연결, i18n 미연결) |
| router.dart | 빈 파일 | `GoRouter(routes: [])` |
| theme.dart | 기본 | AppTheme light/dark (seed color만, TradingColors 미구현) |
| l10n | 최소 | app_en.arb (appTitle만), l10n.yaml 설정 완료, ko/ja/zh/es ARB 없음 |
| features/ | .gitkeep | auth, home, trading 디렉토리만 (6개 누락) |
| core/ | .gitkeep | api, websocket, utils 디렉토리만 (storage 누락) |
| analysis_options.yaml | 완료 | flutter_lints + custom_lint + riverpod_lint |

### 2.2 서버 API 정합성 참조

| 서버 구성요소 | 클라이언트 대응 | 참조 |
|-------------|--------------|------|
| ApiResponse `{data, error, meta}` | `ApiResponse<T>` 제네릭 모델 | `server/app/schemas/common.py` |
| ErrorResponse `{error: {code, message, details?, correlation_id?}}` | `ApiException` 에러 모델 | `server/app/schemas/error.py` |
| WS `ws://server/ws/v1?token=jwt` | `WsClient` 연결 관리자 | `server/app/schemas/ws.py` |
| WS 채널 8종 (ticker, orderbook 등) | 채널별 구독/해제 메서드 | v1-12 설계서 |
| JWT access(30분) + refresh(14일) | Dio 인터셉터 자동 갱신 | v1-5 설계서 |

---

## 3. 프로젝트 디렉토리 구조

```
client/lib/
├── main.dart                          # 앱 진입점
├── app/
│   ├── app.dart                       # CoinTraderApp 위젯 (MaterialApp.router)
│   ├── router.dart                    # GoRouter 설정 + 라우트 정의
│   └── theme.dart                     # Material 3 테마 + TradingColors 확장
│
├── core/
│   ├── api/
│   │   ├── dio_client.dart            # Dio 팩토리 함수 (buildDio)
│   │   ├── api_exception.dart         # Freezed ApiException (서버 에러 코드 매핑)
│   │   └── interceptors/
│   │       ├── auth_interceptor.dart   # Bearer 토큰 주입
│   │       ├── refresh_interceptor.dart # 401 → 토큰 갱신 → 재시도
│   │       └── error_interceptor.dart  # 에러 응답 → ApiException 변환
│   ├── websocket/
│   │   ├── ws_client.dart             # WebSocket 연결/구독/해제 관리
│   │   ├── ws_message.dart            # Freezed WS 메시지 타입
│   │   └── ws_connection_state.dart   # 연결 상태 enum
│   ├── storage/
│   │   ├── secure_storage.dart        # flutter_secure_storage 래퍼 (토큰)
│   │   └── app_preferences.dart       # SharedPreferences 래퍼 (설정)
│   ├── models/
│   │   ├── api_response.dart          # Freezed ApiResponse<T>
│   │   └── app_error.dart             # Freezed AppError
│   ├── providers/
│   │   ├── dio_provider.dart          # @Riverpod(keepAlive: true) Dio 인스턴스
│   │   ├── ws_provider.dart           # @Riverpod(keepAlive: true) WsClient
│   │   ├── storage_provider.dart      # @Riverpod(keepAlive: true) SecureStorage, AppPreferences
│   │   └── auth_state_provider.dart   # AsyncNotifierProvider<User?> (인증 상태)
│   ├── constants/
│   │   └── constants.dart             # API_BASE_URL, WS_URL, 타임아웃 등
│   └── utils/
│       └── extensions.dart            # Dart 확장 유틸리티
│
├── features/                          # Feature-first 구조 (§11 참조)
│   ├── auth/                          # 인증 (로그인/회원가입/비밀번호)
│   │   ├── models/                    # Freezed 모델 (AuthTokens, User 등)
│   │   ├── repositories/             # Dio 기반 API 호출
│   │   ├── providers/                # @riverpod 프로바이더
│   │   ├── screens/                  # Screen 위젯
│   │   └── widgets/                  # Feature 전용 위젯
│   ├── home/                          # 홈 (코인 목록 + 관심 코인)
│   ├── trading/                       # 트레이딩 (차트 + 호가 + 주문)
│   ├── exchange/                      # 거래소 설정 (API 키 관리)
│   ├── ai_trading/                    # AI 자동매매 대시보드
│   ├── portfolio/                     # 자산/포트폴리오
│   ├── history/                       # 매매 내역
│   ├── notifications/                 # 알림
│   └── settings/                      # 설정 (언어, 테마, 프로필)
│
├── shared/
│   ├── models/                        # 공유 도메인 모델 (User, Coin 등)
│   │   └── .gitkeep
│   └── widgets/                       # 공유 위젯 (로딩, 에러, 빈 상태)
│       └── .gitkeep
│
└── l10n/
    ├── app_en.arb                     # 영어 (템플릿)
    ├── app_ko.arb                     # 한국어
    ├── app_ja.arb                     # 일본어
    ├── app_zh.arb                     # 중국어
    └── app_es.arb                     # 스페인어
```

---

## 4. GoRouter 라우팅 구조

### 4.1 네비게이션 아키텍처

PRD §8 네비게이션 규칙에 따라 **5탭 Bottom Navigation + ShellRoute** 구조를 사용한다.

```
GoRouter
├── /splash                          # 스플래시 (토큰 확인 → 자동 리다이렉트)
├── /login                           # 로그인
├── /register                        # 회원가입
├── /forgot-password                 # 비밀번호 찾기
│
├── ShellRoute (ScaffoldWithNavBar)  # Bottom Navigation Shell
│   ├── /home                        # 탭 0: 홈 (코인 목록)
│   ├── /trading                     # 탭 1: 트레이딩
│   │   └── /trading/:coinId         # 코인 상세 (차트+호가+주문)
│   ├── /ai-trading                  # 탭 2: AI 매매 대시보드
│   ├── /portfolio                   # 탭 3: 자산
│   └── /more                        # 탭 4: 더보기
│       ├── /more/exchanges          # 거래소 설정
│       ├── /more/history            # 매매 내역
│       ├── /more/notifications      # 알림
│       ├── /more/settings           # 설정
│       ├── /more/profile            # 프로필 수정
│       └── /more/terms              # 이용약관 (WebView)
```

### 4.2 라우트 설계 상세

```dart
// app/router.dart

final routerProvider = Provider<GoRouter>((ref) {
  final authState = ref.watch(authStateProvider);

  return GoRouter(
    initialLocation: '/splash',
    debugLogDiagnostics: kDebugMode,
    redirect: (context, state) {
      final isAuthenticated = authState.isAuthenticated;
      final isAuthRoute = state.matchedLocation.startsWith('/login') ||
          state.matchedLocation.startsWith('/register') ||
          state.matchedLocation.startsWith('/forgot-password');
      final isSplash = state.matchedLocation == '/splash';

      if (isSplash) return null; // 스플래시는 자체 리다이렉트
      if (!isAuthenticated && !isAuthRoute) return '/login';
      if (isAuthenticated && isAuthRoute) return '/home';
      return null;
    },
    routes: [
      GoRoute(path: '/splash', builder: (_, __) => const SplashScreen()),
      GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/register', builder: (_, __) => const RegisterScreen()),
      GoRoute(path: '/forgot-password', builder: (_, __) => const ForgotPasswordScreen()),

      // Bottom Navigation Shell
      StatefulShellRoute.indexedStack(
        builder: (_, __, navigationShell) => ScaffoldWithNavBar(navigationShell: navigationShell),
        branches: [
          // 탭 0: 홈
          StatefulShellBranch(routes: [
            GoRoute(path: '/home', builder: (_, __) => const HomeScreen()),
          ]),
          // 탭 1: 트레이딩
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/trading',
              builder: (_, __) => const TradingScreen(),
              routes: [
                GoRoute(path: ':coinId', builder: (_, state) =>
                    TradingDetailScreen(coinId: state.pathParameters['coinId']!)),
              ],
            ),
          ]),
          // 탭 2: AI 매매
          StatefulShellBranch(routes: [
            GoRoute(path: '/ai-trading', builder: (_, __) => const AiTradingScreen()),
          ]),
          // 탭 3: 자산
          StatefulShellBranch(routes: [
            GoRoute(path: '/portfolio', builder: (_, __) => const PortfolioScreen()),
          ]),
          // 탭 4: 더보기
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/more',
              builder: (_, __) => const MoreScreen(),
              routes: [
                GoRoute(path: 'exchanges', builder: (_, __) => const ExchangeSettingsScreen()),
                GoRoute(path: 'history', builder: (_, __) => const HistoryScreen()),
                GoRoute(path: 'notifications', builder: (_, __) => const NotificationsScreen()),
                GoRoute(path: 'settings', builder: (_, __) => const SettingsScreen()),
                GoRoute(path: 'profile', builder: (_, __) => const ProfileScreen()),
                GoRoute(path: 'terms', builder: (_, __) => const TermsScreen()),
              ],
            ),
          ]),
        ],
      ),
    ],
  );
});
```

### 4.3 인증 가드 흐름

```
앱 시작
    │
    ▼
SplashScreen
    │
    ├─ SecureStorage에서 refresh token 확인
    │   ├─ 없음 → /login 리다이렉트
    │   └─ 있음 → POST /api/v1/auth/refresh
    │       ├─ 성공 → authState 갱신 → /home 리다이렉트
    │       └─ 실패 → 토큰 삭제 → /login 리다이렉트
    │
GoRouter.redirect (이후 모든 네비게이션)
    │
    ├─ isAuthenticated == false && 보호된 경로 → /login
    ├─ isAuthenticated == true && 인증 경로 → /home
    └─ 그 외 → null (통과)
```

### 4.4 Bottom Navigation Bar 스펙

| 인덱스 | 라벨 | 아이콘 | 경로 |
|-------|------|-------|------|
| 0 | 홈 | Icons.home_outlined / filled | /home |
| 1 | 트레이딩 | Icons.candlestick_chart_outlined / filled | /trading |
| 2 | AI 매매 | Icons.smart_toy_outlined / filled | /ai-trading |
| 3 | 자산 | Icons.account_balance_wallet_outlined / filled | /portfolio |
| 4 | 더보기 | Icons.more_horiz_outlined / more_horiz | /more |

---

## 5. Material 3 테마 설계

### 5.1 기본 테마

기존 `theme.dart`의 seed color 구조를 유지하면서 TradingColors ThemeExtension을 추가한다.

```dart
// app/theme.dart

class AppTheme {
  AppTheme._();

  static const _seedColorLight = Color(0xFF1261C4);
  static const _seedColorDark = Color(0xFF42A5F5);
  static const _darkBackground = Color(0xFF0D0D1A);

  static ThemeData get light => ThemeData(
    colorSchemeSeed: _seedColorLight,
    useMaterial3: true,
    extensions: [TradingColors.korean], // 한국식 기본
  );

  static ThemeData get dark => ThemeData(
    colorSchemeSeed: _seedColorDark,
    useMaterial3: true,
    brightness: Brightness.dark,
    scaffoldBackgroundColor: _darkBackground,
    extensions: [TradingColors.koreanDark],
  );

  // 가격 색상 모드에 따라 테마 변경
  static ThemeData lightWith(TradingColors colors) =>
      light.copyWith(extensions: [colors]);
  static ThemeData darkWith(TradingColors colors) =>
      dark.copyWith(extensions: [colors]);
}
```

### 5.2 TradingColors ThemeExtension

PRD §8 설정 화면 "가격 색상(한국식/글로벌)" 요구사항을 지원한다.

```dart
class TradingColors extends ThemeExtension<TradingColors> {
  final Color buyColor;      // 매수/상승
  final Color sellColor;     // 매도/하락
  final Color holdColor;     // 보합

  const TradingColors({
    required this.buyColor,
    required this.sellColor,
    required this.holdColor,
  });

  // 한국식: 빨강=상승, 파랑=하락 (한국 거래소 관행)
  static const korean = TradingColors(
    buyColor: Color(0xFFD24F45),
    sellColor: Color(0xFF1261C4),
    holdColor: Color(0xFF9E9E9E),
  );
  static const koreanDark = TradingColors(
    buyColor: Color(0xFFEF5350),
    sellColor: Color(0xFF42A5F5),
    holdColor: Color(0xFF9E9E9E),
  );

  // 글로벌: 초록=상승, 빨강=하락 (Binance, Coinbase 등)
  static const global = TradingColors(
    buyColor: Color(0xFF4CAF50),
    sellColor: Color(0xFFD24F45),
    holdColor: Color(0xFF9E9E9E),
  );
  static const globalDark = TradingColors(
    buyColor: Color(0xFF66BB6A),
    sellColor: Color(0xFFEF5350),
    holdColor: Color(0xFF9E9E9E),
  );

  @override
  TradingColors copyWith({Color? buyColor, Color? sellColor, Color? holdColor}) {
    return TradingColors(
      buyColor: buyColor ?? this.buyColor,
      sellColor: sellColor ?? this.sellColor,
      holdColor: holdColor ?? this.holdColor,
    );
  }

  @override
  TradingColors lerp(covariant TradingColors? other, double t) {
    if (other == null) return this;
    return TradingColors(
      buyColor: Color.lerp(buyColor, other.buyColor, t)!,
      sellColor: Color.lerp(sellColor, other.sellColor, t)!,
      holdColor: Color.lerp(holdColor, other.holdColor, t)!,
    );
  }
}

// 사용 예시: Theme.of(context).extension<TradingColors>()!.buyColor
```

### 5.3 테마 모드 Provider

```dart
// 사용자 설정에 따라 테마 모드와 가격 색상 모드를 관리
enum PriceColorMode { korean, global }

// themeProvider: ThemeMode (system/light/dark)
// priceColorModeProvider: PriceColorMode (korean/global)
// → main.dart에서 조합하여 MaterialApp에 전달
```

---

## 6. i18n 다국어 설정

### 6.1 설정

기존 `l10n.yaml` 설정을 유지한다:

```yaml
arb-dir: lib/l10n
template-arb-file: app_en.arb
output-localization-file: app_localizations.dart
output-class: AppLocalizations
nullable-getter: false
```

### 6.2 지원 언어

| 코드 | 언어 | ARB 파일 | Phase |
|------|------|---------|-------|
| en | English | app_en.arb (템플릿) | v1-23 |
| ko | 한국어 | app_ko.arb | v1-23 |
| ja | 日本語 | app_ja.arb | v1-23 (기본 키만) |
| zh | 中文 | app_zh.arb | v1-23 (기본 키만) |
| es | Español | app_es.arb | v1-23 (기본 키만) |

### 6.3 기본 번역 키 (v1-23 범위)

앱 인프라 + 네비게이션 + 인증 화면에 필요한 최소 키만 정의한다. 각 feature 구현 태스크에서 키를 추가한다.

```json
// app_en.arb (템플릿, 약 30개 키)
{
  "@@locale": "en",
  "appTitle": "CoinTrader",

  // 네비게이션
  "navHome": "Home",
  "navTrading": "Trading",
  "navAiTrading": "AI Trading",
  "navPortfolio": "Portfolio",
  "navMore": "More",

  // 인증
  "loginTitle": "Login",
  "registerTitle": "Sign Up",
  "emailLabel": "Email",
  "passwordLabel": "Password",
  "loginButton": "Login",
  "registerButton": "Sign Up",
  "forgotPassword": "Forgot Password?",
  "orLoginWith": "Or login with",

  // 공통
  "loading": "Loading...",
  "retry": "Retry",
  "cancel": "Cancel",
  "confirm": "Confirm",
  "save": "Save",
  "delete": "Delete",
  "search": "Search",
  "noData": "No data available",
  "errorGeneric": "Something went wrong. Please try again.",
  "connectionLost": "Connection lost. Reconnecting...",

  // 더보기
  "moreExchanges": "Exchange Settings",
  "moreHistory": "Trade History",
  "moreNotifications": "Notifications",
  "moreSettings": "Settings",
  "moreProfile": "Profile",
  "moreTerms": "Terms of Service"
}
```

### 6.4 사용법

```dart
// main.dart에서 설정
MaterialApp.router(
  localizationsDelegates: AppLocalizations.localizationsDelegates,
  supportedLocales: AppLocalizations.supportedLocales,
  locale: ref.watch(localeProvider), // 사용자 선택 또는 시스템 로케일
  ...
)

// 위젯에서 사용
Text(AppLocalizations.of(context).navHome)
```

---

## 7. Riverpod 프로바이더 아키텍처

> **작성: code-architect**

### 7.1 코드 생성 전략

- `@riverpod` 어노테이션 사용 (riverpod_generator)
- 생성 파일: `*.g.dart` (`build_runner` 실행)
- `@Riverpod(keepAlive: true)` → core 인프라 (dio, storage, ws) — 앱 수명 내내 유지
- `@riverpod` (기본 autoDispose) → feature provider — 화면 이탈 시 해제

```bash
cd client && dart run build_runner build --delete-conflicting-outputs
```

### 7.2 프로바이더 의존성 그래프

```
[Leaf — no deps]
flutterSecureStorageProvider ──→ FlutterSecureStorage()
sharedPreferencesProvider    ──→ SharedPreferences.getInstance()  ← AsyncNotifierProvider

[Storage wrappers — keepAlive: true]
secureStorageProvider  ──→ SecureStorage(ref.watch(flutterSecureStorageProvider))
appPreferencesProvider ──→ AppPreferences(ref.watch(sharedPreferencesProvider))

[Network — keepAlive: true]
dioClientProvider ──→ buildDio(secureStorage: ref.watch(secureStorageProvider))

[WebSocket — keepAlive: true]
wsClientProvider          ──→ WsClient(secureStorage: ref.watch(secureStorageProvider))
wsConnectionStateProvider ──→ StreamProvider (WsClient.connectionStateStream)

[Auth — app-level single source of truth]
authStateProvider ──→ AsyncNotifierProvider<User?>
  reads: secureStorageProvider (토큰 저장/로드)
  reads: dioClientProvider (API 호출)

[Feature repositories — @riverpod (autoDispose)]
authRepositoryProvider ──→ AuthRepository(dio: ref.watch(dioClientProvider))
coinRepositoryProvider ──→ CoinRepository(dio: ref.watch(dioClientProvider))
... 각 feature별 repository provider

[WS stream families — @riverpod (autoDispose)]
tickerStreamProvider(exchange, market)    ──→ StreamProvider.family (WsClient 채널)
orderbookStreamProvider(exchange, market) ──→ StreamProvider.family
```

### 7.3 Provider 분류

| 분류 | keepAlive | 위치 | 예시 |
|------|-----------|------|------|
| 인프라 | true | `core/providers/` | dio, ws, storage |
| 인증 상태 | true | `core/providers/` | authStateProvider |
| Repository | false | `features/*/repositories/` | authRepository |
| Feature State | false | `features/*/providers/` | coinListProvider |
| WS Stream | false | `features/*/providers/` | tickerStreamProvider.family |

---

## 8. Dio HTTP 클라이언트 설계

> **작성: code-architect**

### 8.1 Dio 팩토리 (dio_client.dart)

```dart
Dio buildDio(SecureStorage storage, {String? baseUrl}) {
  final dio = Dio(BaseOptions(
    baseUrl: baseUrl ?? AppConstants.apiBaseUrl,
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 30),
    headers: {'Content-Type': 'application/json'},
  ));

  // 인터셉터 체인 순서 (실행 순서):
  // 1. AuthInterceptor    — Bearer 토큰 주입
  // 2. RefreshInterceptor — 401 → 토큰 갱신 → 재시도
  // 3. ErrorInterceptor   — 에러 응답 → ApiException 변환
  // 4. LogInterceptor     — kDebugMode에서만 활성화
  dio.interceptors.addAll([
    AuthInterceptor(storage),
    RefreshInterceptor(storage, onUnauthorized: logout),
    ErrorInterceptor(),
    if (kDebugMode) LogInterceptor(requestBody: true, responseBody: true),
  ]);
  return dio;
}
```

**환경변수 오버라이드**: `flutter run --dart-define=API_BASE_URL=http://localhost:8000`

### 8.2 인터셉터 체인

```
Request 흐름:
  App Code → AuthInterceptor.onRequest (토큰 주입) → Server

Response 흐름 (성공):
  Server → ErrorInterceptor.onResponse (통과) → App Code

Response 흐름 (401):
  Server → RefreshInterceptor.onError (토큰 갱신 + 재시도) → App Code
         → 갱신 실패 시: 토큰 삭제 → onUnauthorized() → /login 리다이렉트

Response 흐름 (기타 에러):
  Server → ErrorInterceptor.onError (ApiException 변환) → App Code
```

### 8.3 AuthInterceptor

- `onRequest`: SecureStorage에서 access_token 읽어 `Authorization: Bearer {token}` 헤더 추가
- Skip 경로: `/auth/refresh`, `/auth/login`, `/auth/register`

### 8.4 RefreshInterceptor (핵심)

```dart
class RefreshInterceptor extends Interceptor {
  final SecureStorage _storage;
  final VoidCallback onUnauthorized;
  final Dio _refreshDio; // 인터셉터 없는 별도 Dio 인스턴스 (순환 방지)

  Completer<void>? _refreshLock; // 동시 갱신 방지 lock

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode != 401) return handler.next(err);

    // 이미 refresh 중이면 완료 대기 후 원래 요청 재시도
    if (_refreshLock != null) {
      await _refreshLock!.future;
      return handler.resolve(await _retry(err.requestOptions));
    }

    _refreshLock = Completer();
    try {
      final refreshToken = await _storage.readRefreshToken();
      if (refreshToken == null) throw Exception('no_refresh_token');

      final response = await _refreshDio.post('/api/v1/auth/refresh',
        data: {'refresh_token': refreshToken});

      // Refresh Token Rotation: 새 access + refresh 모두 저장
      await _storage.saveTokens(
        accessToken: response.data['data']['access_token'],
        refreshToken: response.data['data']['refresh_token'],
      );
      _refreshLock!.complete();
      _refreshLock = null;

      return handler.resolve(await _retry(err.requestOptions));
    } catch (_) {
      _refreshLock?.completeError(_);
      _refreshLock = null;
      await _storage.clearTokens();
      onUnauthorized(); // → authStateProvider 초기화 → GoRouter /login 리다이렉트
      handler.next(err);
    }
  }
}
```

### 8.5 ErrorInterceptor

서버 에러 응답 `{ "error": { "code": "...", "message": "...", "details": [...] } }` → `ApiException` 변환:

```dart
@override
void onError(DioException err, ErrorInterceptorHandler handler) {
  if (err.type == DioExceptionType.connectionTimeout ||
      err.type == DioExceptionType.receiveTimeout) {
    throw const ApiException.timeout();
  }
  if (err.type == DioExceptionType.connectionError) {
    throw ApiException.network(message: err.message ?? 'Network error');
  }
  final data = err.response?.data;
  if (data is Map && data['error'] != null) {
    throw ApiException.server(
      code: data['error']['code'],
      message: data['error']['message'],
      statusCode: err.response?.statusCode,
    );
  }
  handler.next(err);
}
```

### 8.6 ApiException (Freezed)

```dart
@freezed
class ApiException with _$ApiException implements Exception {
  const factory ApiException.server({
    required String code,
    required String message,
    int? statusCode,
  }) = ServerException;
  const factory ApiException.network({required String message}) = NetworkException;
  const factory ApiException.timeout() = TimeoutException;
  const factory ApiException.unauthorized() = UnauthorizedException;
}
```

---

## 9. WebSocket 클라이언트 설계

> **작성: code-architect**

### 9.1 서버 WS 프로토콜 정합성

서버 WS Hub (v1-12)와 정확히 매칭되는 프로토콜:

| 방향 | 메시지 | 예시 |
|------|--------|------|
| Client→Server | subscribe | `{"action":"subscribe","channel":"ticker","exchange":"upbit","market":"KRW-BTC"}` |
| Client→Server | unsubscribe | `{"action":"unsubscribe","channel":"ticker","exchange":"upbit","market":"KRW-BTC"}` |
| Client→Server | ping | `{"action":"ping"}` |
| Server→Client | connected | `{"action":"connected","conn_id":"...","timestamp":"..."}` |
| Server→Client | subscribed | `{"action":"subscribed","channel":"ticker","exchange":"upbit","market":"KRW-BTC"}` |
| Server→Client | pong | `{"action":"pong","timestamp":"..."}` |
| Server→Client | error | `{"action":"error","code":"...","message":"..."}` |
| Server→Client | data | 채널별 실시간 데이터 (ticker, orderbook, trades 등) |

### 9.2 WsConnectionState

```dart
enum WsConnectionState { disconnected, connecting, connected, reconnecting }
```

PRD §5.2 연결 상태 UI 매핑:
- `connected` → 녹색 인디케이터
- `connecting` / `reconnecting` → 황색 + 스피너 + "재연결 중" 배너
- `disconnected` → 적색 + "연결 끊김" 배너

### 9.3 WsClient

```dart
class WsClient {
  WebSocketChannel? _channel;
  final StreamController<WsMessage> _messageController = StreamController.broadcast();
  final StreamController<WsConnectionState> _stateController = StreamController.broadcast();

  // 채널별 스트림 분배
  final Map<String, StreamController<WsMessage>> _channelControllers = {};

  // 현재 구독 목록 (재연결 시 자동 재구독용)
  final Set<Map<String, dynamic>> _activeSubscriptions = {};

  // 재연결 설정
  static const _maxRetryDelay = Duration(seconds: 30);
  int _retryCount = 0;
  Timer? _heartbeatTimer;
  Timer? _reconnectTimer;

  Future<void> connect() async {
    _stateController.add(WsConnectionState.connecting);
    final token = await _secureStorage.readAccessToken();
    _channel = WebSocketChannel.connect(Uri.parse('$wsUrl?token=$token'));
    await _channel!.ready;
    _stateController.add(WsConnectionState.connected);
    _retryCount = 0;
    _startHeartbeat();
    _listenMessages();
    _resubscribeAll(); // 재연결 시 기존 구독 복원
  }

  Future<void> disconnect() async { ... }

  void subscribe(String channel, {String? exchange, String? market}) {
    final params = {'action': 'subscribe', 'channel': channel};
    if (exchange != null) params['exchange'] = exchange;
    if (market != null) params['market'] = market;
    _activeSubscriptions.add(params);
    _send(params);
  }

  void unsubscribe(String channel, {String? exchange, String? market}) {
    final params = {'action': 'unsubscribe', 'channel': channel};
    if (exchange != null) params['exchange'] = exchange;
    if (market != null) params['market'] = market;
    _activeSubscriptions.removeWhere((s) =>
      s['channel'] == channel && s['exchange'] == exchange && s['market'] == market);
    _send(params);
  }

  /// 특정 채널의 메시지 스트림 (StreamProvider.family에서 사용)
  Stream<WsMessage> channelStream(String channelKey) {
    return _channelControllers
      .putIfAbsent(channelKey, () => StreamController.broadcast())
      .stream;
  }

  Stream<WsConnectionState> get connectionStateStream => _stateController.stream;
}
```

### 9.4 재연결 로직 (지수 백오프)

```
연결 끊김 감지
    │
    ▼
_stateController.add(reconnecting)
    │
    ▼
지연 대기: min(2^retryCount, 30) 초
    │  1s → 2s → 4s → 8s → 16s → 30s (max)
    ▼
connect() 재시도
    │
    ├─ 성공 → _resubscribeAll() (기존 구독 복원) → retryCount = 0
    └─ 실패 → retryCount++ → 재시도 루프
```

### 9.5 Heartbeat

- 30초마다 `{"action": "ping"}` 전송
- 10초 내 `{"action": "pong"}` 미수신 시 강제 재연결 트리거
- 앱 백그라운드 전환 시 heartbeat 중단 + disconnect (WidgetsBindingObserver)
- 앱 포그라운드 복귀 시 자동 reconnect

### 9.6 WsMessage (Freezed)

```dart
@freezed
class WsMessage with _$WsMessage {
  const factory WsMessage({
    String? action,
    String? channel,
    String? exchange,
    String? market,
    String? connId,
    String? code,
    String? message,
    Map<String, dynamic>? data,
    String? timestamp,
  }) = _WsMessage;
  factory WsMessage.fromJson(Map<String, dynamic> json) => _$WsMessageFromJson(json);
}
```

---

## 10. 로컬 저장소 계층

> **작성: code-architect**

### 10.1 저장소 역할 분담

| 저장소 | 라이브러리 | 용도 | 데이터 예시 |
|--------|-----------|------|-----------|
| **SecureStorage** | flutter_secure_storage | 민감 데이터 (OS Keychain/Keystore) | JWT 토큰 |
| **AppPreferences** | SharedPreferences | 앱 설정 (비민감) | 테마, 로케일, 가격 색상 모드 |
| **Hive** | hive_flutter | 캐시 데이터 (구조화) | 코인 목록, 관심 코인 |

### 10.2 SecureStorage (flutter_secure_storage 래퍼)

```dart
class SecureStorage {
  final FlutterSecureStorage _storage;

  static const _accessTokenKey = 'access_token';
  static const _refreshTokenKey = 'refresh_token';

  Future<void> saveTokens({required String accessToken, required String refreshToken});
  Future<String?> readAccessToken();
  Future<String?> readRefreshToken();
  Future<void> clearTokens();
}
```

### 10.3 AppPreferences (SharedPreferences 래퍼)

```dart
class AppPreferences {
  final SharedPreferences _prefs;

  // 테마
  Future<void> setThemeMode(ThemeMode mode);
  ThemeMode getThemeMode(); // sync (SharedPreferences는 동기 read 가능)

  // 로케일
  Future<void> setLocale(String localeCode);
  String? getLocale();

  // 가격 색상
  Future<void> setPriceColorScheme(String scheme); // 'korean' | 'global'
  String getPriceColorScheme();

  // 마지막 선택 거래소
  Future<void> setLastSelectedExchange(String exchange);
  String? getLastSelectedExchange();
}
```

### 10.4 Hive (캐시)

- Box: `coins_cache`, `watchlist_cache`
- TypeAdapter: `@HiveType` 코드 생성
- TTL 관리: 저장 시 `_cachedAt` timestamp 포함, 읽을 때 만료 확인
- v1-23 범위: Hive 초기화 + Box 등록만. 실제 캐시 모델은 각 feature 태스크에서 추가

---

## 11. Features 디렉토리 구조

> **작성: code-architect**

### 11.1 공통 내부 구조 (모든 feature 동일 패턴)

```
features/{feature}/
├── models/          # Freezed 모델 (해당 feature 전용)
├── repositories/    # Dio 기반 API 호출 (@riverpod)
├── providers/       # @riverpod 프로바이더 (상태 관리)
├── screens/         # Screen 위젯 (GoRouter에서 참조)
└── widgets/         # Feature 전용 위젯
```

### 11.2 Feature별 Freezed 모델

**auth/models/**
```dart
@freezed class AuthTokens { String accessToken; String refreshToken; int expiresIn; }
@freezed class User { String id; String email; String nickname; String? avatarUrl; bool is2faEnabled; }
@freezed class SocialLoginRequest { String provider; String idToken; }
```

**home/models/**
```dart
@freezed class Coin { String id; String symbol; String name; String exchange; String market;
                       Decimal? price; Decimal? changeRate24h; Decimal? volume24h; }
```

**trading/models/**
```dart
@freezed class Ticker { String symbol; Decimal price; Decimal changeRate24h; Decimal volume24h; DateTime timestamp; }
@freezed class OrderbookEntry { Decimal price; Decimal size; }
@freezed class Orderbook { String symbol; List<OrderbookEntry> asks; List<OrderbookEntry> bids; }
@freezed class Order { String id; String side; String type; Decimal price; Decimal amount; String status; }
```

**exchange/models/**
```dart
@freezed class ExchangeAccount { String id; String exchange; String label; bool isConnected; DateTime? lastVerified; }
```

**ai_trading/models/**
```dart
@freezed class AiTradingConfig { String id; bool isActive; String exchange; String strategy; Decimal maxAmount; }
@freezed class AiTradingStats { Decimal totalPnl; int totalOrders; Decimal winRate; }
```

**portfolio/models/**
```dart
@freezed class PortfolioSummary { Decimal totalAsset; Decimal totalPnl; List<ExchangePortfolio> exchanges; }
@freezed class CoinHolding { String symbol; Decimal amount; Decimal avgBuyPrice; Decimal currentPrice; Decimal pnlRate; }
```

**settings/models/**
```dart
@freezed class AppSettings { ThemeMode themeMode; String locale; String priceColorScheme; bool pushEnabled; }
```

### 11.3 Feature별 파일 목록 (스캐폴딩 대상)

| Feature | repositories/ | providers/ | screens/ |
|---------|--------------|-----------|---------|
| **auth** | auth_repository.dart | auth_provider.dart | splash_screen, login_screen, register_screen, email_verify_screen, forgot_password_screen |
| **home** | coin_repository.dart | coin_list_provider, watchlist_provider | home_screen |
| **trading** | order_repository.dart, trading_repository.dart | ticker_provider (WS family), orderbook_provider (WS family), order_provider | trading_screen |
| **exchange** | exchange_repository.dart | exchange_provider | exchange_screen |
| **ai_trading** | ai_trading_repository.dart | ai_trading_provider | ai_trading_screen |
| **portfolio** | portfolio_repository.dart | portfolio_provider | portfolio_screen |
| **history** | order_history_repository.dart | order_history_provider | history_screen |
| **notifications** | notification_repository.dart | notification_provider | notifications_screen |
| **settings** | — | settings_provider (AppSettings AsyncNotifier), theme_provider | settings_screen, profile_screen |

---

## 12. main.dart 진입점 설계

### 12.1 초기화 순서

```dart
// main.dart
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 1. 로컬 저장소 초기화
  await Hive.initFlutter();
  final secureStorage = SecureStorageService();
  final preferences = await SharedPreferences.getInstance();

  // 2. ProviderScope에 override 주입
  runApp(
    ProviderScope(
      overrides: [
        secureStorageProvider.overrideWithValue(secureStorage),
        sharedPreferencesProvider.overrideWithValue(preferences),
      ],
      child: const CoinTraderApp(),
    ),
  );
}
```

### 12.2 CoinTraderApp 위젯

```dart
// app/app.dart
class CoinTraderApp extends ConsumerWidget {
  const CoinTraderApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final themeMode = ref.watch(themeModeProvider);
    final priceColorMode = ref.watch(priceColorModeProvider);
    final locale = ref.watch(localeProvider);

    return MaterialApp.router(
      title: 'CoinTrader',
      theme: priceColorMode == PriceColorMode.korean
          ? AppTheme.light
          : AppTheme.lightWith(TradingColors.global),
      darkTheme: priceColorMode == PriceColorMode.korean
          ? AppTheme.dark
          : AppTheme.darkWith(TradingColors.globalDark),
      themeMode: themeMode,
      routerConfig: router,
      locale: locale,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
    );
  }
}
```

---

## 13. 구현 파일 목록

### ST1: Riverpod 프로바이더 아키텍처 (code-architect)
| 파일 | 역할 |
|------|------|
| `core/providers/dio_provider.dart` | `@Riverpod(keepAlive: true)` Dio 인스턴스 |
| `core/providers/ws_provider.dart` | `@Riverpod(keepAlive: true)` WsClient |
| `core/providers/storage_provider.dart` | `@Riverpod(keepAlive: true)` SecureStorage, AppPreferences |
| `core/providers/auth_state_provider.dart` | AsyncNotifierProvider\<User?\> 인증 상태 |
| `core/constants/constants.dart` | API_BASE_URL, WS_URL, 타임아웃 (`--dart-define` 오버라이드) |

### ST2: Dio HTTP 클라이언트 (code-architect)
| 파일 | 역할 |
|------|------|
| `core/api/dio_client.dart` | `buildDio()` 팩토리 함수 |
| `core/api/interceptors/auth_interceptor.dart` | Bearer 토큰 주입 |
| `core/api/interceptors/refresh_interceptor.dart` | 401 → 토큰 갱신 (Completer lock) → 재시도 |
| `core/api/interceptors/error_interceptor.dart` | 서버 에러 → ApiException 변환 |
| `core/api/api_exception.dart` | Freezed ApiException (server, network, timeout, unauthorized) |
| `core/models/api_response.dart` | Freezed ApiResponse\<T\>, AppError |

### ST3: GoRouter 라우팅 (flutter-frontend-expert)
| 파일 | 역할 |
|------|------|
| `app/router.dart` | GoRouter + StatefulShellRoute 설정 (기존 파일 수정) |
| `shared/widgets/scaffold_with_nav_bar.dart` | Bottom Navigation Shell (5탭) |
| `features/auth/screens/splash_screen.dart` | 스플래시 (토큰 확인 → 리다이렉트) |

### ST4: Material 3 테마 (flutter-frontend-expert)
| 파일 | 역할 |
|------|------|
| `app/theme.dart` | AppTheme + TradingColors ThemeExtension (기존 파일 수정) |

### ST5: WebSocket 클라이언트 (code-architect)
| 파일 | 역할 |
|------|------|
| `core/websocket/ws_client.dart` | WS 연결/구독/해제 + 지수 백오프 재연결 + heartbeat |
| `core/websocket/ws_message.dart` | Freezed WsMessage (서버 프로토콜 매칭) |
| `core/websocket/ws_connection_state.dart` | 연결 상태 enum (4상태) |

### ST6: 로컬 저장소 (code-architect)
| 파일 | 역할 |
|------|------|
| `core/storage/secure_storage.dart` | flutter_secure_storage 래퍼 (JWT 토큰) |
| `core/storage/app_preferences.dart` | SharedPreferences 래퍼 (테마, 로케일, 가격 색상) |

### ST7: i18n (flutter-frontend-expert)
| 파일 | 역할 |
|------|------|
| `l10n/app_en.arb` | 영어 (기존 파일 확장, ~30키) |
| `l10n/app_ko.arb` | 한국어 (신규) |
| `l10n/app_ja.arb` | 일본어 (신규, 기본 키만) |
| `l10n/app_zh.arb` | 중국어 (신규, 기본 키만) |
| `l10n/app_es.arb` | 스페인어 (신규, 기본 키만) |

### ST8: main.dart 최종 구성 (flutter-frontend-expert)
| 파일 | 역할 |
|------|------|
| `main.dart` | 진입점: Hive.initFlutter + ProviderScope overrides (기존 파일 수정) |
| `app/app.dart` | CoinTraderApp: MaterialApp.router + 테마/i18n/라우터 통합 (신규) |

### ST9: features 스캐폴딩 (code-architect)
| 파일 | 역할 |
|------|------|
| `features/{9개}/models/` | Freezed 모델 스텁 |
| `features/{9개}/repositories/` | Repository 스텁 (Dio DI) |
| `features/{9개}/providers/` | @riverpod 프로바이더 스텁 |
| `features/{9개}/screens/` | Screen placeholder 위젯 |
| `features/{9개}/widgets/` | 빈 디렉토리 (.gitkeep) |

### ST10: 테스트 환경 구성 (code-review-expert)
| 파일 | 역할 |
|------|------|
| `test/core/api/` | Dio 인터셉터 단위 테스트 |
| `test/core/websocket/` | WsClient 단위 테스트 |
| `test/core/storage/` | 저장소 래퍼 단위 테스트 |
| `integration_test/` | 통합 테스트 설정 + app_test.dart |

---

## 14. 구현 순서

```
ST1 (Riverpod) ─────────────────────────────────┐
                                                  │
ST4 (Theme) ─────────────────────────────────────┤
                                                  │
ST7 (i18n) ──────────────────────────────────────┤
                                                  │
ST1 완료 후:                                       │
├── ST2 (Dio) ──────────────────────────┐        │
├── ST6 (Storage) ──────────────────────┤        │
└── ST9 (Features 스캐폴딩) ────────────┤        │
                                         │        │
ST1+ST2 완료 후:                          │        │
└── ST5 (WebSocket) ────────────────────┤        │
                                         │        │
ST1 완료 + ST4 + ST7 완료 후:             │        │
└── ST3 (GoRouter) ─────────────────────┤        │
                                         │        │
ST3+ST4+ST7+ST8 의존 전체 완료 후:         │        │
└── ST8 (main.dart 최종) ───────────────┤        │
                                         │        │
ST8+ST9 완료 후:                          │        │
└── ST10 (테스트 환경) ─────────────────┘        │
```

**병렬 가능 그룹**:
- **Group A** (독립): ST1, ST4, ST7
- **Group B** (ST1 의존): ST2, ST6, ST9
- **Group C** (ST1+ST2 의존): ST5
- **Group D** (ST3 → ST1+라우팅 필요): ST3
- **Group E** (대부분 완료 후): ST8, ST10

---

## 15. 기술 결정 요약

| 결정 | 선택 | 대안 | 근거 |
|------|------|------|------|
| 라우팅 | GoRouter + StatefulShellRoute | auto_route | pubspec.yaml에 이미 go_router 선언, Flutter 공식 권장 |
| Bottom Nav | StatefulShellRoute.indexedStack | 수동 IndexedStack | GoRouter 공식 패턴, 각 탭 상태 보존 |
| 인증 가드 | GoRouter.redirect | Navigator guard | 선언적, 상태 기반 리다이렉트 |
| 테마 확장 | ThemeExtension<TradingColors> | 별도 상수 클래스 | Material 3 공식 패턴, lerp 지원 |
| 가격 색상 | korean/global 2모드 | 사용자 커스텀 | PRD §8 "가격 색상(한국식/글로벌)" 명시 |
| i18n | flutter_localizations + intl ARB | easy_localization | pubspec.yaml 이미 설정, Flutter 공식 |
| Provider 패턴 | Riverpod 2.x + riverpod_generator | 수동 provider | 코드 생성으로 타입 안전성, riverpod_lint 이미 설정 |
| WS 라이브러리 | web_socket_channel | socket_io_client | pubspec.yaml 이미 선언, 서버가 순수 WS 사용 |
| 토큰 저장 | flutter_secure_storage | Hive encrypted | OS Keychain/Keystore 활용, 보안 최우선 |
| 캐시 저장 | Hive | drift, isar | pubspec.yaml 이미 선언, 가벼운 KV 스토어 적합 |
| 인터셉터 구조 | 개별 파일 (auth/refresh/error) | 단일 파일 | 책임 분리, refresh의 Completer lock 복잡성 격리 |
| 토큰 갱신 | RefreshInterceptor + Completer lock + 별도 Dio | QueuedInterceptor | 동시 401 요청 시 lock 대기 후 재시도, 순환 인터셉터 방지 |
| 환경 설정 | `--dart-define` 오버라이드 | dotenv | 빌드 타임 주입, 런타임 패키지 불필요 |
| WS Heartbeat | 30초 ping, 10초 pong 타임아웃 | 서버 주도 ping | 클라이언트 주도로 네트워크 끊김 즉시 감지 |
| Feature 내부 | models/repositories/providers/screens/widgets | data/domain/presentation | 트레이딩 앱 규모에 적합한 간소화 구조 |
