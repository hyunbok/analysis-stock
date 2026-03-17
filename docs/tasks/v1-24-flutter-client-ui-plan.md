# v1-24 Flutter 클라이언트 UI 화면 구현 — 설계서

> **작성**: project-architect (전체 구조, 화면별 상세 스펙), code-architect (위젯 트리, 상태 관리, 디렉토리 구조)
> **대상 태스크**: v1-24 — Flutter 클라이언트 UI 화면 구현 (M1~M8)
> **현재 상태**: 설계 완료
> **기반**: v1-23 설계서, docs/design-concept.md

---

## 1. 개요

v1-23에서 구축된 Flutter 인프라(Riverpod, Dio, GoRouter, WS, 테마, i18n, feature 스캐폴딩) 위에
실제 UI 화면을 구현한다. 모든 Screen은 현재 placeholder(`TODO`) 상태이며, 이를 design-concept.md 기준으로
완성한다.

**범위**: 10개 서브태스크 (ST1: 공통 UI → ST2~ST10: 각 화면)
**의존성**: v1-23 완료 (feature/v1-23_flutter-project-setup 브랜치)

---

## 2. 기존 코드 현황 분석

### 2.1 v1-23에서 완성된 항목

| 항목 | 파일 | 상태 |
|------|------|------|
| GoRouter + 5탭 ShellRoute | `app/router.dart` | 완성 (인증 가드, redirect) |
| ScaffoldWithNavBar | `shared/widgets/scaffold_with_nav_bar.dart` | 완성 (5탭 NavigationBar) |
| AppTheme + TradingColors | `app/theme.dart` | 완성 (light/dark, korean/global) |
| Dio + 인터셉터 체인 | `core/api/` | 완성 |
| WsClient | `core/websocket/` | 완성 |
| SecureStorage + AppPreferences | `core/storage/` | 완성 |
| AuthState Provider | `core/providers/auth_state_provider.dart` | 완성 |
| i18n (en, ko, ja, zh, es) | `l10n/` | 기본 30키 완성 |
| Feature 스캐폴딩 | `features/*/` | models/repositories/providers/screens 스텁 완성 |

### 2.2 각 Screen 현재 상태

모든 Screen이 placeholder:
```dart
class HomeScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Center(child: Text('Home — TODO')));
  }
}
```

**예외**: `MoreScreen`은 기본 ListView 메뉴 구현 완료.

---

## 3. 디자인 시스템 (공통 컴포넌트)

### 3.1 디렉토리 구조

> code-architect 협업 결정: 카테고리별 서브폴더 구조 채택 (20개 위젯 수준에서 가독성 향상)

```
shared/widgets/
├── scaffold_with_nav_bar.dart          # 기존 (변경 없음)
│
├── price/                              # 가격/수치 표시 위젯
│   ├── price_text.dart                 # 실시간 가격 (플래시 애니메이션, AnimationController 300ms)
│   ├── change_rate_text.dart           # 등락률 (▲▼ + buyColor/sellColor)
│   └── pnl_text.dart                   # 손익 텍스트 (수익색/손실색)
│
├── loading/                            # 로딩 상태 위젯
│   ├── shimmer_box.dart                # 단순 회색 박스 스켈레톤 (width/height/radius)
│   ├── shimmer_list.dart               # 리스트 스켈레톤 (CoinListTile 형태, count 파라미터)
│   └── loading_overlay.dart            # 전체화면 로딩 오버레이 (주문 처리 등)
│
├── states/                             # 상태 표시 위젯 (AsyncValue.when()과 조합)
│   ├── error_view.dart                 # 에러 (아이콘 + 메시지 + 재시도 버튼)
│   └── empty_view.dart                 # 빈 상태 (아이콘 + 안내 텍스트)
│
├── badges/                             # 배지/칩 위젯
│   ├── ai_status_badge.dart            # AI 상태 (ON/OFF/분석중, 펄스 애니메이션)
│   ├── market_regime_chip.dart         # 장세 분류 (추세/횡보/전환)
│   ├── exchange_chip.dart              # 거래소 선택 칩
│   └── order_side_badge.dart           # 매수/매도 뱃지
│
├── connection/                         # WS 연결 상태 위젯
│   └── ws_connection_banner.dart       # 재연결 중/끊김 상단 배너
│
├── coin_icon.dart                      # 코인 아이콘 (CachedNetworkImage + fallback)
├── coin_list_tile.dart                 # 코인 목록 행 (홈+트레이딩 공유)
├── order_button.dart                   # 매수/매도 주문 버튼
├── trade_history_tile.dart             # 매매 내역 행 (내역+AI 로그 공유)
├── app_search_bar.dart                 # 공통 검색바
└── confirm_bottom_sheet.dart           # 확인 다이얼로그 바텀시트
```

**위젯 배치 원칙** (code-architect 합의):
- `shared/widgets/`: 2개 이상 feature에서 사용되는 위젯
- `features/{name}/widgets/`: 해당 feature에서만 사용
- trading 화면은 복잡하므로 feature 내 서브폴더 허용:

```
features/trading/widgets/
├── chart/
│   ├── trading_view_chart.dart       # TradingView WebView 래퍼
│   └── timeframe_chips.dart          # 시간봉 선택 칩 행
├── orderbook/
│   ├── orderbook_widget.dart         # 호가창 전체 (매도+현재가+매수)
│   └── orderbook_row.dart            # 호가창 행 (가격 + 잔량 + 컬러바)
└── order/
    ├── order_form.dart               # 주문 폼 전체
    └── balance_ratio_chips.dart      # 25/50/75/100% 잔고 비율 칩
```

### 3.2 핵심 컴포넌트 스펙

#### PriceText

```dart
/// 실시간 가격 표시 + 변동 시 배경색 플래시 (300ms).
/// Inter tabular figures, 우측 정렬.
///
/// 애니메이션 패턴 (code-architect 설계):
///   AnimationController(300ms) + ColorTween
///   ref.listen(tickerProvider) → 가격 변동 감지 → 플래시 트리거
class PriceText extends StatefulWidget {
  final double price;
  final double? previousPrice;      // 플래시 방향 결정
  final TextStyle? style;
  final String currencySuffix;      // "원" 또는 "KRW"
  const PriceText({required this.price, this.previousPrice, ...});
}
```

- 상승: buyColor 10% opacity 플래시 → AnimatedContainer fade out 300ms
- 하락: sellColor 10% opacity 플래시 → AnimatedContainer fade out 300ms
- 숫자 포맷: 천 단위 콤마 (intl NumberFormat)
- `fontFeatures: [FontFeature.tabularFigures()]` 적용
- 200ms throttle: 너무 빈번한 업데이트 방지 (design-concept.md 명시)

#### ChangeRateText

```dart
/// 등락률 표시 — 방향 화살표 + 색상 자동 적용.
/// "+2.34%" (buyColor) / "-0.87%" (sellColor) / "0.00%" (holdColor)
class ChangeRateText extends StatelessWidget {
  final double rate;
  final TextStyle? style;
  final bool showArrow;             // ▲/▼ 접두사
}
```

#### CoinListTile (shared/widgets/ — 홈+트레이딩 공유)

```dart
/// 코인 목록 행 — 홈 화면 + 트레이딩 코인 선택 목록에서 공유.
/// [코인아이콘 36dp] [코인명 Bold / 심볼 Gray] [현재가 우측 / 등락률 색상]
class CoinListTile extends StatelessWidget {
  final Coin coin;
  final VoidCallback? onTap;
  final VoidCallback? onFavoriteToggle;
  final bool isFavorite;
}
```

#### OrderBookRow (features/trading/widgets/orderbook/ — 트레이딩 전용)

```dart
/// 호가창 행 — 가격 + 잔량 + 비율 컬러 바.
class OrderBookRow extends StatelessWidget {
  final double price;
  final double size;
  final double maxSize;             // 컬러 바 상대 너비 계산
  final bool isBid;                 // true=매수(빨강), false=매도(파랑)
  final VoidCallback? onTap;        // 호가 탭 → 주문창 가격 자동 입력
}
```

#### AsyncValueWidget

```dart
/// AsyncValue를 loading/error/data 3상태로 분기하는 래퍼.
/// 모든 화면에서 일관된 로딩/에러 UX 보장.
class AsyncValueWidget<T> extends StatelessWidget {
  final AsyncValue<T> value;
  final Widget Function(T data) data;
  final Widget? loading;            // null → ShimmerPlaceholder 기본
  final Widget Function(Object error, StackTrace? stack)? error;
}
```

#### ShimmerPlaceholder

```dart
/// 로딩 스켈레톤 — Shimmer Effect (회색 박스 깜빡임).
/// width/height/borderRadius 커스텀 가능.
class ShimmerPlaceholder extends StatelessWidget {
  final double? width;
  final double? height;
  final double borderRadius;
}
```

### 3.3 추가 의존성 (pubspec.yaml)

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `shimmer` | ^3.0.0 | 로딩 스켈레톤 UI |
| `cached_network_image` | ^3.3.0 | 코인 아이콘 캐싱 |
| `flutter_svg` | ^2.0.0 | SVG 아이콘/로고 |

기존 의존성으로 충분한 것:
- 가격 포맷: `intl` (이미 설치) NumberFormat
- 미니차트: `fl_chart` (이미 설치)
- TradingView 차트: `webview_flutter` (이미 설치)

---

## 4. 화면별 상세 설계

### 4.1 ST1: 공통 UI 컴포넌트 및 디자인 시스템 구현

**범위**: shared/widgets/ 전체 + pubspec.yaml 의존성 추가 + i18n 키 추가

**신규 파일 (20개)**:

| 파일 | 역할 |
|------|------|
| `shared/widgets/price/price_text.dart` | 실시간 가격 (플래시 애니메이션) |
| `shared/widgets/price/change_rate_text.dart` | 등락률 (색상 + 화살표) |
| `shared/widgets/price/pnl_text.dart` | 손익 텍스트 |
| `shared/widgets/loading/shimmer_box.dart` | Shimmer 로딩 스켈레톤 |
| `shared/widgets/loading/loading_overlay.dart` | 전체화면 로딩 오버레이 |
| `shared/widgets/states/error_view.dart` | 에러 + 재시도 |
| `shared/widgets/states/empty_view.dart` | 빈 상태 |
| ~~`shared/widgets/states/async_value_widget.dart`~~ | ~~AsyncValue 래퍼~~ (제거: `.when()` 직접 사용 패턴 채택) |
| `shared/widgets/badges/ai_status_badge.dart` | AI 상태 배지 |
| `shared/widgets/badges/market_regime_chip.dart` | 장세 분류 칩 |
| `shared/widgets/badges/exchange_chip.dart` | 거래소 칩 |
| `shared/widgets/badges/order_side_badge.dart` | 매수/매도 뱃지 |
| `shared/widgets/coin_icon.dart` | 코인 아이콘 |
| `shared/widgets/coin_list_tile.dart` | 코인 목록 행 |
| ~~`shared/widgets/order_book_row.dart`~~ | ~~호가창 행~~ (이동: `features/trading/widgets/orderbook/orderbook_row.dart`) |
| `shared/widgets/order_button.dart` | 매수/매도 버튼 |
| `shared/widgets/trade_history_tile.dart` | 매매 내역 행 |
| `shared/widgets/ws_connection_indicator.dart` | WS 연결 상태 |
| `shared/widgets/app_search_bar.dart` | 공통 검색바 |
| `shared/widgets/confirm_bottom_sheet.dart` | 확인 바텀시트 |

**수정 파일**:
- `pubspec.yaml`: shimmer, cached_network_image, flutter_svg 추가

**i18n 추가 키**: 없음 (각 ST에서 화면별 키 추가)

---

### 4.2 ST2: 스플래시 화면 구현

**수정 파일**: `features/auth/screens/splash_screen.dart`

**위젯 트리**:
```
Scaffold
└── Container (gradient: #0D1B3E → #12131A)
    └── Column (mainAxisAlignment: center)
        ├── SvgPicture.asset('assets/icons/logo.svg')  // 앱 로고
        ├── SizedBox(height: 16)
        ├── Text('CoinTrader', style: displayLarge)
        ├── SizedBox(height: 8)
        ├── Text('코인 자동매매 플랫폼', style: bodyMedium)
        ├── SizedBox(height: 48)
        ├── LinearProgressIndicator(minHeight: 3)
        ├── SizedBox(height: 16)
        └── Text('v1.0.0', style: bodySmall)
```

**동작**:
- GoRouter redirect에서 authStateProvider 완료 후 /home 또는 /login 리다이렉트 (기존 로직 유지)
- splash_screen은 순수 UI만 담당 (로직 없음)

**Provider**: 없음 (기존 authStateProvider + GoRouter redirect 활용)

**i18n 추가 키**:
```json
"splashTagline": "코인 자동매매 플랫폼"
```

**신규 에셋**: `assets/icons/logo.svg` (앱 로고 SVG)

---

### 4.3 ST3: 로그인/회원가입 화면 구현

**수정 파일**:
- `features/auth/screens/login_screen.dart`
- `features/auth/screens/register_screen.dart`
- `features/auth/screens/forgot_password_screen.dart`
- `features/auth/screens/email_verify_screen.dart`

**신규 파일**:
- `features/auth/widgets/auth_header.dart` — 로고 + 앱명 + 환영 메시지
- `features/auth/widgets/social_login_buttons.dart` — Google/Apple 소셜 로그인 버튼
- `features/auth/widgets/password_field.dart` — 비밀번호 입력 (토글 visibility)

#### LoginScreen 위젯 트리

```
Scaffold
└── SafeArea
    └── SingleChildScrollView
        └── Padding (24dp)
            └── Column
                ├── AuthHeader (로고 + 앱명 + 환영 메시지)
                ├── SizedBox(height: 32)
                ├── TextFormField (email, keyboardType: email)
                ├── SizedBox(height: 16)
                ├── PasswordField (obscure + toggle)
                ├── Align (right)
                │   └── TextButton ('비밀번호 찾기' → /forgot-password)
                ├── SizedBox(height: 24)
                ├── FilledButton.tonal (full width, '로그인')
                │   └── 로딩 상태: CircularProgressIndicator (small)
                ├── SizedBox(height: 24)
                ├── Row (Divider — '또는' — Divider)
                ├── SizedBox(height: 24)
                ├── SocialLoginButtons (Google, Apple)
                ├── SizedBox(height: 16)
                └── TextButton ('회원가입' → /register)
```

#### RegisterScreen 위젯 트리

```
Scaffold
├── AppBar (← 뒤로가기)
└── SafeArea
    └── SingleChildScrollView
        └── Padding (24dp)
            └── Column
                ├── Text ('회원가입', headlineMedium)
                ├── SizedBox(height: 8)
                ├── Text ('이메일로 가입합니다', bodyMedium)
                ├── SizedBox(height: 32)
                ├── TextFormField (이메일)
                ├── SizedBox(height: 16)
                ├── TextFormField (닉네임)
                ├── SizedBox(height: 16)
                ├── PasswordField (비밀번호)
                ├── SizedBox(height: 16)
                ├── PasswordField (비밀번호 확인)
                ├── SizedBox(height: 8)
                ├── CheckboxListTile (이용약관 동의)
                ├── SizedBox(height: 24)
                └── FilledButton.tonal ('회원가입')
```

**Provider 연동**:
- 기존 `features/auth/providers/auth_provider.dart` 활용
- 로그인/회원가입 시 authStateProvider.login() / register() 호출
- Form validation: 이메일 형식, 비밀번호 길이(8+), 비밀번호 확인 일치

**i18n 추가 키**:
```json
"welcomeTitle": "CoinTrader에 오신 것을 환영합니다",
"registerSubtitle": "이메일로 가입합니다",
"nicknameLabel": "닉네임",
"passwordConfirmLabel": "비밀번호 확인",
"agreeTerms": "이용약관 및 개인정보 처리방침에 동의합니다",
"emailVerifyTitle": "이메일 인증",
"emailVerifySent": "인증 메일이 발송되었습니다",
"emailVerifyResend": "인증 메일 재전송",
"forgotPasswordTitle": "비밀번호 찾기",
"forgotPasswordDesc": "가입한 이메일 주소를 입력하세요",
"resetPasswordButton": "비밀번호 재설정 링크 전송",
"socialGoogle": "Google로 계속하기",
"socialApple": "Apple로 계속하기"
```

---

### 4.4 ST4: 메인/홈 화면 구현

**수정 파일**: `features/home/screens/home_screen.dart`

**신규 파일**:
- `features/home/widgets/exchange_tab_bar.dart` — 거래소 탭 (Upbit, CoinOne)
- `features/home/widgets/coin_search_delegate.dart` — 코인 검색 로직
- `core/providers/market_state_provider.dart` — SelectedExchange/SelectedMarket (keepAlive, 교차 feature 공유)
- `core/utils/format_utils.dart` — 가격/등락률/수량 포맷 유틸

#### HomeScreen 위젯 트리

```
Scaffold
├── AppBar
│   ├── title: Text('CoinTrader')
│   └── actions: [WsConnectionBanner, IconButton(알림), IconButton(프로필)]
└── Column
    ├── ExchangeTabBar ([Upbit] [CoinOne] — TabBar + TabBarView)
    ├── Padding
    │   └── AppSearchBar (코인 검색 → 탭 시 전체 코인 목록 탐색 모드)
    ├── _SortHeader (코인명 | 현재가 | 변동률 | 거래량 — 정렬 토글)
    └── Expanded
        └── watchlistProvider.when(...)     ← 기본 뷰: 관심 코인 (design-concept.md §7.3)
            ├── loading: ShimmerList(count: 8)
            ├── error: ErrorView(onRetry: ...)
            └── data: RefreshIndicator
                └── ListView.builder
                    └── CoinListTile (관심 코인)
                        └── onTap: context.go('/trading/${coin.id}')
    // 검색바 활성화 시: coinListProvider로 전환 (전체 코인 탐색)
```

**상태 관리**:
- `selectedExchangeProvider` (core/providers/, keepAlive: true): 선택된 거래소 ('upbit' | 'coinone')
- `selectedMarketProvider` (core/providers/, keepAlive: true): 선택된 마켓 (홈→트레이딩 공유)
- 기존 `coinListProvider`: exchange + query 파라미터 반영
- 기존 `tickerProvider` (WS StreamProvider.family): 실시간 시세 업데이트
- 기존 `watchlistProvider`: 관심 코인 상태

**실시간 업데이트**:
- coinListProvider 로드 → 각 코인 market에 대해 tickerStreamProvider 구독
- ticker 수신 시 CoinListTile 내 PriceText/ChangeRateText 자동 갱신
- 가격 플래시: PriceText의 previousPrice로 방향 감지

**정렬**:
- 로컬 정렬 (Provider에서 처리): 코인명(가나다), 현재가(높/낮), 등락률(높/낮), 거래량(높/낮)
- `coinSortProvider` (StateProvider<CoinSort>) 추가

**i18n 추가 키**:
```json
"homeSearchHint": "코인 검색...",
"homeSortName": "코인명",
"homeSortPrice": "현재가",
"homeSortChange": "변동률",
"homeSortVolume": "거래량",
"homeNoCoins": "코인이 없습니다"
```

---

### 4.5 ST5: 트레이딩 화면 구현 (TradingView 차트/호가/주문)

**수정 파일**:
- `features/trading/screens/trading_screen.dart` (TradingScreen + TradingDetailScreen)

**신규 파일**:
- `features/trading/widgets/trading_header.dart` — 현재가 + 등락률 고정 헤더
- `features/trading/widgets/chart/trading_view_chart.dart` — TradingView WebView 래퍼
- `features/trading/widgets/chart/timeframe_chips.dart` — 시간봉 선택 칩
- `features/trading/widgets/orderbook/orderbook_widget.dart` — 호가창 전체
- `features/trading/widgets/orderbook/orderbook_row.dart` — 호가창 행 (가격+잔량+컬러바)
- `features/trading/widgets/order/order_form.dart` — 주문 폼 전체
- `features/trading/widgets/order/balance_ratio_chips.dart` — 25/50/75/100% 잔고 비율 칩
- `features/trading/providers/order_form_provider.dart` — 주문 폼 상태
- `assets/html/trading_view.html` — TradingView Lightweight Charts HTML

#### TradingScreen 위젯 트리 (코인 선택 전)

```
Scaffold
├── AppBar (title: '트레이딩')
└── Center
    └── Column
        ├── Icon(Icons.candlestick_chart, size: 64)
        ├── Text('코인을 선택하세요')
        └── TextButton('홈에서 코인 선택' → /home)
```

#### TradingDetailScreen 위젯 트리

```
Scaffold
├── AppBar
│   ├── leading: BackButton
│   ├── title: Text('BTC/KRW')
│   └── actions: [IconButton(즐겨찾기 ★), IconButton(더보기 ...)]
└── Column
    ├── TradingHeader (현재가 105,234,000 + 등락 ▲ +2.34% — 항상 표시)
    ├── TabBar ([차트] [호가창] [주문])
    └── Expanded
        └── TabBarView
            ├── ChartTab (TradingView WebView + TimeframeChips)
            ├── OrderbookTab (매도/매수 호가 + 현재가 구분선)
            └── OrderTab (매수/매도 SegmentedButton + 가격/수량 입력 + 주문 버튼)
```

#### ChartTab — TradingView 통합

```
Column
├── Expanded
│   └── WebViewWidget (TradingView Lightweight Charts)
│       ├── initialUrl: 'assets/html/tradingview.html'
│       ├── JavaScriptChannel: 'FlutterBridge'
│       └── onPageFinished: _initChart(symbol, theme, interval)
└── TimeframeChips ([1분] [5분] [15분] [30분] [1시] [4시] [일] [주])
```

TradingView HTML/JS는 `assets/html/tradingview.html`에 번들. Flutter → JS 통신:
- `setSymbol(exchange, market)` — 심볼 변경
- `setInterval(interval)` — 시간봉 변경
- `setTheme(isDark)` — 다크/라이트 전환
- `addIndicator(name, params)` — 지표 오버레이 추가

JS → Flutter 통신 (JavaScriptChannel):
- `onCrosshairMove(price, time)` — 크로스헤어 이동

#### OrderbookTab 위젯 트리

```
Column
├── Row (매도잔량 | 가격 | 건수 — 헤더)
├── Expanded
│   └── ListView (매도 호가 10건 — 파랑)
├── Container (현재가 구분선 — 볼드)
├── Expanded
│   └── ListView (매수 호가 10건 — 빨강)
└── Row (매수잔량 | 가격 | 건수 — 푸터)
```

- orderbookProvider (WS StreamProvider.family) 연동
- 호가 행 탭 → orderFormProvider의 price 자동 입력
- 잔량 바: maxSize 대비 비율로 컬러 바 너비 결정

#### OrderTab 위젯 트리

```
Column
├── SegmentedButton ([매수] [매도])
├── SizedBox(height: 16)
├── DropdownButtonFormField (주문 유형: 지정가 / 시장가)
├── SizedBox(height: 12)
├── TextFormField (가격 — 지정가 시) + StepButton(↑↓)
├── SizedBox(height: 12)
├── TextFormField (수량)
├── SizedBox(height: 8)
├── QuantityRatioChips ([25%] [50%] [75%] [100%])
├── SizedBox(height: 16)
├── Row (주문 총액: xxx원 / 사용 가능: xxx원)
├── Spacer
└── OrderButton ('BTC 매수 주문' — buyColor or sellColor)
    └── onTap: confirmBottomSheet → orderProvider.placeOrder()
```

**Provider**:
- `tradingTabProvider` (StateProvider<int>): 선택된 탭 인덱스 (0=차트, 1=호가, 2=주문)
- `orderFormProvider` (@riverpod NotifierProvider): OrderForm 상태 (side, type, price, quantity)
  - **`ref.keepAlive()` 패턴**: TradingDetailScreen 내 탭(차트/호가/주문) 전환 시 폼 상태 유지
  ```dart
  @riverpod
  class OrderForm extends _$OrderForm {
    KeepAliveLink? _keepAlive;
    @override
    OrderFormState build() {
      _keepAlive = ref.keepAlive(); // 탭 전환 동안 유지
      ref.onDispose(() => _keepAlive?.close());
      return OrderFormState.initial();
    }
    // TradingDetailScreen 이탈 시 외부에서 ref.invalidate(orderFormProvider) 호출 → 자동 해제
  }
  ```
- 기존 `tickerProvider`, `orderbookProvider`, `orderProvider` 활용

**i18n 추가 키**:
```json
"tradingSelectCoin": "코인을 선택하세요",
"tradingSelectCoinHint": "홈에서 코인 선택",
"tradingTabChart": "차트",
"tradingTabOrderbook": "호가창",
"tradingTabOrder": "주문",
"tradingCurrentPrice": "현재가",
"orderbookAskHeader": "매도 잔량",
"orderbookBidHeader": "매수 잔량",
"orderbookPrice": "가격",
"orderbookCount": "건수",
"orderBuy": "매수",
"orderSell": "매도",
"orderTypeLimit": "지정가",
"orderTypeMarket": "시장가",
"orderPrice": "가격",
"orderQuantity": "수량",
"orderTotal": "주문 총액",
"orderAvailable": "사용 가능",
"orderBuyButton": "{coin} 매수 주문",
"orderSellButton": "{coin} 매도 주문",
"orderConfirmTitle": "주문 확인",
"orderConfirmMessage": "{side} {coin} {quantity}개를 {price}에 주문합니다",
"timeframe1m": "1분",
"timeframe5m": "5분",
"timeframe15m": "15분",
"timeframe30m": "30분",
"timeframe1h": "1시",
"timeframe4h": "4시",
"timeframe1d": "일",
"timeframe1w": "주"
```

---

### 4.6 ST6: 거래소 설정 화면 구현

**수정 파일**: `features/exchange/screens/exchange_screen.dart`

**신규 파일**:
- `features/exchange/widgets/exchange_account_card.dart` — 연결된 거래소 카드
- `features/exchange/widgets/add_exchange_bottom_sheet.dart` — API 키 등록 바텀시트
- `features/exchange/widgets/security_info_card.dart` — 보안 안내 카드

#### ExchangeScreen 위젯 트리

```
Scaffold
├── AppBar (title: '거래소 설정', leading: ← )
└── SingleChildScrollView
    └── Padding (16dp)
        └── Column
            ├── Text ('연결된 거래소', titleLarge)
            ├── SizedBox(height: 12)
            ├── AsyncValueWidget(exchangeProvider)
            │   └── data: Column
            │       └── ExchangeAccountCard × N
            │           ├── 거래소 아이콘 + 이름
            │           ├── API Key: ****1234 (마스킹)
            │           ├── 마지막 검증: 2026-03-17
            │           └── Row ([수정] [삭제])
            ├── SizedBox(height: 16)
            ├── OutlinedButton.icon (+ 거래소 추가)
            │   └── onTap: showAddExchangeBottomSheet
            ├── SizedBox(height: 24)
            └── SecurityInfoCard
                └── Text ('API 키는 AES-256-GCM 방식으로 암호화 저장됩니다')
```

#### AddExchangeBottomSheet 위젯 트리

```
DraggableScrollableSheet
└── Padding (24dp)
    └── Column
        ├── Text ('거래소 추가', headlineSmall)
        ├── SizedBox(height: 16)
        ├── SegmentedButton (Upbit / CoinOne)
        ├── SizedBox(height: 16)
        ├── TextFormField (Access Key)
        ├── SizedBox(height: 12)
        ├── TextFormField (Secret Key, obscure + 토글)
        ├── SizedBox(height: 24)
        └── FilledButton ('연결 테스트 후 저장')
            └── 로딩: CircularProgressIndicator
```

**Provider**: 기존 `exchangeProvider` 활용

**i18n 추가 키**:
```json
"exchangeTitle": "거래소 설정",
"exchangeConnected": "연결된 거래소",
"exchangeAdd": "거래소 추가",
"exchangeAccessKey": "Access Key",
"exchangeSecretKey": "Secret Key",
"exchangeTestAndSave": "연결 테스트 후 저장",
"exchangeEdit": "수정",
"exchangeDelete": "삭제",
"exchangeDeleteConfirm": "이 거래소 연결을 삭제하시겠습니까?",
"exchangeLastVerified": "마지막 검증: {date}",
"exchangeSecurityNote": "API 키는 AES-256-GCM 방식으로 암호화 저장됩니다",
"exchangeUpbit": "업비트",
"exchangeCoinone": "코인원"
```

---

### 4.7 ST7: AI 매매 대시보드 화면 구현

**수정 파일**: `features/ai_trading/screens/ai_trading_screen.dart`

**신규 파일**:
- `features/ai_trading/widgets/ai_master_switch.dart` — AI 전체 ON/OFF 스위치
- `features/ai_trading/widgets/regime_summary_card.dart` — 현재 장세 요약
- `features/ai_trading/widgets/daily_pnl_card.dart` — 오늘의 손익 + 미니 차트
- `features/ai_trading/widgets/coin_ai_setting_tile.dart` — 코인별 AI 설정 행
- `features/ai_trading/widgets/ai_trade_log_tile.dart` — 최근 AI 매매 로그 행
- `features/ai_trading/providers/ai_master_switch_provider.dart` — AI 전체 ON/OFF 상태
  - **기존 `AiTradingNotifier.toggle(configId)`과의 구분**: toggle()은 개별 코인 AI 설정 활성/비활성 (config 단위). 마스터 스위치는 전체 AI 매매 일괄 ON/OFF (별도 API: `POST /api/v1/ai-trading/master-toggle`). 별도 Provider로 분리하여 SRP 유지.

#### AiTradingScreen 위젯 트리

```
Scaffold
├── AppBar (title: 'AI 자동매매')
└── RefreshIndicator
    └── SingleChildScrollView
        └── Padding (16dp)
            └── Column
                ├── AiMasterSwitch
                │   └── Card (전체 AI 매매 [ON ●───] Switch)
                │       └── ON 전환 시: confirmBottomSheet ('AI 자동매매를 시작합니다')
                ├── SizedBox(height: 16)
                ├── RegimeSummaryCard
                │   ├── Row (추세 75% | 횡보 20% | 전환 5%)
                │   │   └── MarketRegimeChip × 3
                │   └── Text ('마지막 분석: 13:25:00')
                ├── SizedBox(height: 16)
                ├── DailyPnlCard
                │   ├── PnlText (+124,500 원 (+1.24%))
                │   └── SizedBox (height: 80)
                │       └── fl_chart LineChart (오늘 손익 추이)
                ├── SizedBox(height: 16)
                ├── Text ('코인별 AI 설정', titleMedium)
                ├── CoinAiSettingTile × N
                │   ├── CoinIcon + 코인명
                │   ├── Switch (개별 ON/OFF)
                │   ├── Text (전략: TrendMA 눌림목)
                │   └── Text (진입가: 105,000,000)
                ├── SizedBox(height: 16)
                ├── Text ('최근 AI 매매 로그', titleMedium)
                └── AiTradeLogTile × N (최근 10건)
                    ├── Text (13:20 BTC 매수 103,000)
                    └── AiStatusBadge
```

**AI 상태 배지 (AiStatusBadge)**:
- AI ON: `#00BCD4` 민트색 배경 + "AI 작동중"
- AI OFF: 회색 배경 + "중지됨"
- 분석중: 펄스 애니메이션 + "분석중..."

**장세 표시 (MarketRegimeChip)**:
- Trend: `#F23645` + "추세장"
- Range: `#9E9E9E` + "횡보장"
- Transition: `#FF9800` + "전환장"

**Provider**: 기존 `aiTradingProvider` + `aiTradingStatsProvider` 활용

**i18n 추가 키**:
```json
"aiTitle": "AI 자동매매",
"aiMasterSwitch": "전체 AI 매매",
"aiConfirmStart": "AI 자동매매를 시작합니다.\n최대 투자금: {amount}원",
"aiCurrentRegime": "현재 장세",
"aiLastAnalysis": "마지막 분석: {time}",
"aiDailyPnl": "오늘의 손익",
"aiCoinSettings": "코인별 AI 설정",
"aiRecentLogs": "최근 AI 매매 로그",
"aiStatusOn": "AI 작동중",
"aiStatusOff": "중지됨",
"aiStatusAnalyzing": "분석중...",
"regimeTrend": "추세장",
"regimeRange": "횡보장",
"regimeTransition": "전환장",
"aiStrategy": "전략: {name}",
"aiEntryPrice": "진입가: {price}"
```

---

### 4.8 ST8: 포트폴리오 및 매매 내역 화면 구현

**수정 파일**:
- `features/portfolio/screens/portfolio_screen.dart`
- `features/history/screens/history_screen.dart`

**신규 파일**:
- `features/portfolio/widgets/total_asset_card.dart` — 총 자산 요약 카드
- `features/portfolio/widgets/exchange_portfolio_section.dart` — 거래소별 자산
- `features/portfolio/widgets/coin_holding_tile.dart` — 보유 코인 행
- `features/portfolio/widgets/portfolio_pie_chart.dart` — 자산 비율 파이 차트
- `features/history/widgets/history_summary_card.dart` — 요약 카드 (총손익, 승률, 거래수)
- `features/history/widgets/history_filter_chips.dart` — 기간 필터 칩
- `features/history/widgets/date_group_header.dart` — 날짜 그룹 헤더

#### PortfolioScreen 위젯 트리

```
Scaffold
├── AppBar (title: '자산')
└── RefreshIndicator
    └── SingleChildScrollView
        └── Padding (16dp)
            └── Column
                ├── TotalAssetCard
                │   ├── Text ('총 자산', bodyMedium)
                │   ├── Text ('12,345,678 원', headlineLarge, bold)
                │   └── PnlText (+345,600원 (+2.88%))
                ├── SizedBox(height: 16)
                ├── PortfolioPieChart (fl_chart PieChart)
                ├── SizedBox(height: 16)
                ├── ExchangePortfolioSection × N
                │   ├── Text ('업비트', titleMedium)
                │   └── CoinHoldingTile × N
                │       ├── CoinIcon + 코인명
                │       ├── 보유수량 / 평균단가
                │       └── 현재가 / 수익률
```

#### HistoryScreen 위젯 트리

```
Scaffold
├── AppBar (title: '매매 내역')
└── Column
    ├── HistoryFilterChips ([이번달] [지난달] [직접 선택])
    ├── HistorySummaryCard
    │   ├── 총 손익: +345,600원
    │   ├── 승률: 68.4%
    │   └── 거래수: 24건
    ├── TabBar ([주문 내역] [체결 내역])
    └── Expanded
        └── TabBarView
            ├── OrderHistoryList (주문 내역)
            └── TradeHistoryList (체결 내역)
                └── ListView.builder (날짜 그룹)
                    ├── DateGroupHeader ('2026-03-04')
                    └── TradeHistoryTile × N
```

**Provider**: 기존 `portfolioProvider` + `orderHistoryProvider` 활용

**i18n 추가 키**:
```json
"portfolioTitle": "자산",
"portfolioTotalAsset": "총 자산",
"portfolioHolding": "보유 수량",
"portfolioAvgPrice": "평균 단가",
"portfolioPnlRate": "수익률",
"historyTitle": "매매 내역",
"historyFilterThisMonth": "이번달",
"historyFilterLastMonth": "지난달",
"historyFilterCustom": "직접 선택",
"historyTotalPnl": "총 손익",
"historyWinRate": "승률",
"historyTradeCount": "거래수",
"historyTabOrders": "주문 내역",
"historyTabTrades": "체결 내역",
"historyAiTrade": "AI매매",
"historyManualTrade": "수동"
```

---

### 4.9 ST9: 프로필 수정 화면 구현

**수정 파일**: `features/settings/screens/profile_screen.dart`

**신규 파일**:
- `features/settings/widgets/avatar_picker.dart` — 프로필 아바타 선택 + 카메라/갤러리
- `features/settings/providers/profile_edit_provider.dart` — 프로필 수정 폼 상태

#### ProfileScreen 위젯 트리

```
Scaffold
├── AppBar (title: '프로필 수정', actions: [TextButton('저장')])
└── SingleChildScrollView
    └── Padding (24dp)
        └── Column
            ├── Center
            │   └── AvatarPicker
            │       ├── CircleAvatar (96dp, CachedNetworkImage)
            │       └── Positioned
            │           └── IconButton (카메라 아이콘)
            ├── SizedBox(height: 24)
            ├── TextFormField (이메일 — readOnly, disabled)
            ├── SizedBox(height: 16)
            ├── TextFormField (닉네임 — editable)
            ├── SizedBox(height: 32)
            └── OutlinedButton ('비밀번호 변경' → 바텀시트)
```

**i18n 추가 키**:
```json
"profileTitle": "프로필 수정",
"profileAvatar": "프로필 사진",
"profileChangeAvatar": "사진 변경",
"profileNickname": "닉네임",
"profileEmail": "이메일",
"profileChangePassword": "비밀번호 변경",
"profileSaved": "프로필이 저장되었습니다"
```

---

### 4.10 ST10: 설정 화면 구현

**수정 파일**: `features/settings/screens/settings_screen.dart`

**신규 파일**:
- `features/settings/widgets/settings_section.dart` — 설정 섹션 래퍼
- `features/settings/widgets/settings_tile.dart` — 설정 행 (trailing: switch/dropdown/chevron)

#### SettingsScreen 위젯 트리

```
Scaffold
├── AppBar (title: '설정')
└── ListView
    ├── SettingsSection (title: '앱 설정')
    │   ├── SettingsTile (테마 — DropdownButton: 다크/라이트/시스템)
    │   ├── SettingsTile (언어 — DropdownButton: 한국어/English/...)
    │   ├── SettingsTile (가격 색상 — DropdownButton: 한국식/글로벌)
    │   └── SettingsTile (알림 — Switch)
    ├── SettingsSection (title: '알림 설정')
    │   ├── SettingsTile (가격 알림 — Switch)
    │   ├── SettingsTile (AI 매매 알림 — Switch)
    │   └── SettingsTile (체결 알림 — Switch)
    ├── SettingsSection (title: '보안')
    │   ├── SettingsTile (비밀번호 변경 → chevron)
    │   └── SettingsTile (생체 인증 — Switch)
    ├── SettingsSection (title: '정보')
    │   ├── SettingsTile (버전: v1.0.0)
    │   ├── SettingsTile (이용약관 → /more/terms)
    │   └── SettingsTile (개인정보 처리방침 → chevron)
    └── Padding
        └── OutlinedButton ('로그아웃' — destructive color)
```

**MoreScreen 수정 상세**:
- 하드코딩 영어 텍스트 → i18n 키 참조로 교체 ('Profile' → `context.l10n.moreProfile`, 'Exchange' → `context.l10n.moreExchange` 등)
- 아이콘 업데이트: 각 메뉴 항목에 Material Symbols Rounded 아이콘 매칭 (person, currency_exchange, smart_toy, history, settings)
- ListTile trailing: `Icon(Icons.chevron_right)` 통일

**MoreScreen i18n 추가 키**:
```json
"moreProfile": "프로필",
"moreExchange": "거래소 설정",
"moreAiSettings": "AI 매매 설정",
"moreHistory": "매매 내역",
"moreSettings": "설정"
```

**Provider**: 기존 `settingsProvider` 활용 (themeMode, locale, priceColorMode)

**i18n 추가 키**:
```json
"settingsTitle": "설정",
"settingsAppSection": "앱 설정",
"settingsTheme": "테마",
"settingsThemeDark": "다크",
"settingsThemeLight": "라이트",
"settingsThemeSystem": "시스템",
"settingsLanguage": "언어",
"settingsPriceColor": "가격 색상",
"settingsPriceColorKorean": "한국식",
"settingsPriceColorGlobal": "글로벌",
"settingsNotifications": "알림",
"settingsNotifSection": "알림 설정",
"settingsNotifPrice": "가격 알림",
"settingsNotifAi": "AI 매매 알림",
"settingsNotifTrade": "체결 알림",
"settingsSecuritySection": "보안",
"settingsChangePassword": "비밀번호 변경",
"settingsBiometric": "생체 인증",
"settingsInfoSection": "정보",
"settingsVersion": "버전",
"settingsTerms": "이용약관",
"settingsPrivacy": "개인정보 처리방침",
"settingsLogout": "로그아웃",
"settingsLogoutConfirm": "로그아웃 하시겠습니까?"
```

---

## 5. 상태 관리 패턴 정리

> code-architect 설계 기반

### 5.1 UI 로컬 상태 vs Riverpod Provider

| 상태 유형 | 관리 방식 | 예시 |
|----------|----------|------|
| 데이터 페칭 (서버/WS) | Riverpod AsyncNotifier/StreamProvider | coinList, ticker, orderbook |
| 화면 간 공유 상태 | Riverpod StateProvider/NotifierProvider | selectedExchange, themeMode |
| 화면 내 UI 전용 | StatefulWidget 로컬 | TabController, TextEditingController, FocusNode |
| 폼 상태 (주문 등) | Riverpod StateNotifier | orderFormProvider (side, type, price, quantity) |
| 검색/필터 | Riverpod StateProvider | searchQueryProvider, coinSortProvider |

### 5.2 Riverpod Provider 패턴 상세 (code-architect 결정)

| 데이터 유형 | 어노테이션 | keepAlive | 근거 |
|------------|-----------|-----------|------|
| 실시간 시세 (ticker/orderbook) | `@riverpod Stream` | false (autoDispose) | 화면 이탈 시 WS 구독 자동 해제 |
| 코인 목록 | `@riverpod Future` + family | false (autoDispose) | exchange, query 파라미터 조합별 캐시 |
| 관심 코인 | `@Riverpod(keepAlive: true)` | true | 홈 탭이 항상 유지되므로 데이터 보존 |
| AI 설정/stats | `@riverpod AsyncNotifier` | false | invalidateSelf 패턴으로 갱신 |
| 설정 (테마/로케일) | `@Riverpod(keepAlive: true)` | true | MaterialApp에서 watch → 앱 수명 유지 |

### 5.3 교차 Feature 공유 상태 (code-architect 제안 반영)

홈 탭에서 선택한 거래소/코인이 트레이딩 탭에도 유지되어야 하므로 `keepAlive: true` Provider 추가:

```dart
// core/providers/market_state_provider.dart (신규)

@Riverpod(keepAlive: true)
class SelectedExchange extends _$SelectedExchange {
  @override
  String build() => 'upbit';  // 기본값
  void select(String exchange) => state = exchange;
}

@Riverpod(keepAlive: true)
class SelectedMarket extends _$SelectedMarket {
  @override
  String build() => 'KRW-BTC';  // 기본값
  void select(String market) => state = market;
}
```

- 홈에서 거래소 탭 전환 → `selectedExchangeProvider.select('coinone')`
- 홈에서 코인 탭 → `selectedMarketProvider.select('KRW-ETH')` → 트레이딩 탭에서 유지
- 기존 `features/home/providers/selected_exchange_provider.dart`는 제거 → core로 승격

### 5.4 AsyncValue 통일 패턴

모든 데이터 페칭은 `AsyncValue<T>`로 관리하고, `.when()` 또는 `AsyncValueWidget`으로 렌더링한다:

```dart
// Provider
@riverpod
Future<List<Coin>> coinList(CoinListRef ref, ...) async {
  return ref.watch(coinRepositoryProvider).getCoins(...);
}

// Screen — .when() 직접 사용 (표준 패턴)
ref.watch(coinListProvider(exchange: exchange)).when(
  loading: () => const ShimmerList(),
  error: (e, _) => ErrorView(onRetry: () => ref.refresh(coinListProvider(exchange: exchange).future)),
  data: (coins) => CoinListView(coins: coins),
)
```

### 5.5 폼 유효성 검사 패턴 (code-architect 설계)

```dart
// 로그인/회원가입: Form + GlobalKey<FormState> + TextFormField validator
// 주문: orderFormProvider (StateNotifier) + 서버 사이드 검증 결과 반영
// 패턴: Form.validate() → true 시 Provider 호출 → AsyncValue.guard()
```

### 5.6 가격/수량 포맷 유틸 (code-architect 설계)

```dart
// core/utils/format_utils.dart (신규)

class FormatUtils {
  /// 한국 원화 포맷: 105,234,000
  static String formatKrw(double price) =>
      NumberFormat('#,###', 'ko_KR').format(price);

  /// 등락률 포맷: +2.34% / -0.87%
  static String formatRate(double rate) =>
      '${rate >= 0 ? '+' : ''}${rate.toStringAsFixed(2)}%';

  /// 코인 수량 포맷: 소수점 최대 8자리, trailing zero 제거
  static String formatCoinAmount(double amount) =>
      amount.toStringAsFixed(8).replaceAll(RegExp(r'\.?0+$'), '');
}
```

---

## 6. TradingView 차트 통합 상세

### 6.1 HTML 번들 구조

`assets/html/tradingview.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="lightweight-charts.standalone.production.js"></script>
  <!-- 이 JS 파일은 assets/html/ 에 함께 번들: assets/html/lightweight-charts.standalone.production.js -->
  <style>
    body { margin: 0; padding: 0; overflow: hidden; }
    #chart { width: 100%; height: 100%; }
  </style>
</head>
<body>
  <div id="chart"></div>
  <script>
    let chart, candleSeries, volumeSeries;

    function initChart(options) {
      // options: { theme, symbol, interval, bgColor }
      chart = LightweightCharts.createChart(document.getElementById('chart'), {
        layout: { background: { type: 'solid', color: options.bgColor } },
        // ...
      });
      candleSeries = chart.addCandlestickSeries({ ... });
      volumeSeries = chart.addHistogramSeries({ ... });
    }

    function setTheme(isDark) { /* 테마 전환 */ }
    function setData(candles) { candleSeries.setData(candles); }
    function updateCandle(candle) { candleSeries.update(candle); }
    function setInterval(interval) { /* 서버에 캔들 데이터 요청 */ }

    // Flutter에 이벤트 전달
    chart.subscribeCrosshairMove((param) => {
      FlutterBridge.postMessage(JSON.stringify({ type: 'crosshair', ...param }));
    });
  </script>
</body>
</html>
```

### 6.2 Flutter ↔ WebView 통신 (code-architect 설계)

```dart
// features/trading/widgets/chart/trading_view_chart.dart

class TradingViewChart extends ConsumerStatefulWidget {
  final String symbol;      // 예: "UPBIT:KRWBTC"
  final String exchange;
  const TradingViewChart({required this.symbol, required this.exchange, super.key});
}

class _TradingViewChartState extends ConsumerState<TradingViewChart> {
  late final WebViewController _controller;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel('FlutterBridge', onMessageReceived: _onBridgeMessage)
      ..loadFlutterAsset('assets/html/trading_view.html');
  }

  // Flutter → JS
  void changeSymbol(String symbol) =>
      _controller.runJavaScript('window.tvWidget?.setSymbol("$symbol", null)');
  void changeInterval(String interval) =>
      _controller.runJavaScript('window.tvWidget?.chart().setResolution("$interval")');
  void applyTheme(bool isDark) =>
      _controller.runJavaScript('applyTheme(${isDark ? '"dark"' : '"light"'})');

  // JS → Flutter: 호가 클릭 시 주문창 가격 자동 입력
  void _onBridgeMessage(JavaScriptMessage msg) {
    final data = jsonDecode(msg.message) as Map<String, dynamic>;
    if (data['type'] == 'price_tap') {
      ref.read(selectedOrderPriceProvider.notifier).state =
          double.parse(data['price'].toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    // 테마 변경 감지 → WebView에 적용
    ref.listen(themeModeProvider, (_, next) {
      applyTheme(next == ThemeMode.dark);
    });
    return WebViewWidget(controller: _controller);
  }
}
```

**TradingView HTML 파일 위치**: `client/assets/html/trading_view.html` (로컬 asset)
- 이유: 외부 URL은 네트워크 의존성 + CSP 이슈. TradingView Lightweight Charts를 로컬 HTML로 임베드

### 6.3 캔들 데이터 흐름

```
1. 화면 진입: REST API → 과거 캔들 200~500개 로드 → setData()
2. 실시간: WS ticker → 최신 캔들 업데이트 → updateCandle()
3. 시간봉 변경: REST API → 해당 interval 캔들 로드 → setData()
```

---

## 7. fl_chart 통합 패턴 (code-architect 설계)

### 7.1 포트폴리오 도넛 차트

```dart
// features/portfolio/widgets/portfolio_pie_chart.dart
PieChart(
  PieChartData(
    sections: holdings.map((h) => PieChartSectionData(
      value: h.totalAsset,
      color: _coinColor(h.symbol),  // 코인별 고정 색상 맵
      title: h.symbol,
      radius: 60,
    )).toList(),
    centerSpaceRadius: 50,  // 도넛 구멍
  ),
)
```

### 7.2 AI 대시보드 손익 미니 라인 차트

```dart
// features/ai_trading/widgets/pnl_mini_chart.dart
LineChart(
  LineChartData(
    lineBarsData: [
      LineChartBarData(
        spots: pnlData.map((p) => FlSpot(p.timestamp, p.pnl)).toList(),
        color: totalPnl >= 0 ? tradingColors.buyColor : tradingColors.sellColor,
        isCurved: true,
        belowBarData: BarAreaData(show: true, color: barColor.withAlpha(30)),
      ),
    ],
    gridData: FlGridData(show: false),
    titlesData: FlTitlesData(show: false),  // 미니차트: 축 제거
    borderData: FlBorderData(show: false),
  ),
)
```

---

## 8. i18n 키 총 추가 목록

v1-23 기존 30키 + v1-24 추가 약 100키 = 총 약 130키

| 화면 | 추가 키 수 |
|------|-----------|
| ST2 스플래시 | 1 |
| ST3 로그인/회원가입 | 13 |
| ST4 홈 | 6 |
| ST5 트레이딩 | 28 |
| ST6 거래소 설정 | 12 |
| ST7 AI 매매 | 16 |
| ST8 포트폴리오/내역 | 16 |
| ST9 프로필 | 6 |
| ST10 설정 + MoreScreen | 27 |
| **합계** | **~125** |

각 ST에서 해당 화면의 i18n 키를 app_en.arb에 추가하고, app_ko.arb도 동시 업데이트한다.
ja/zh/es는 영어 키값을 임시 복사하고, Phase 2(M12)에서 번역 검수한다.

---

## 9. 테스트 전략

### 8.1 위젯 테스트

| 대상 | 테스트 항목 | 예상 건수 |
|------|-----------|----------|
| 공통 위젯 (ST1) | PriceText 플래시, ChangeRateText 색상, ShimmerPlaceholder, AsyncValueWidget 3상태 | ~20 |
| 로그인/회원가입 (ST3) | Form validation, 로딩 상태, 에러 상태, 소셜 로그인 버튼 렌더링 | ~10 |
| 홈 (ST4) | CoinListTile 렌더링, 검색 필터, 정렬, 빈 상태 | ~8 |
| 트레이딩 (ST5) | 탭 전환, 호가창 렌더링, 주문 폼 validation, SegmentedButton 전환 | ~12 |
| AI 대시보드 (ST7) | 마스터 스위치, 장세 표시, 코인별 설정 | ~8 |
| 기타 (ST6,8,9,10) | 렌더링 + 인터랙션 기본 검증 | ~12 |
| **합계** | | **~70** |

### 8.2 테스트 패턴

```dart
// ProviderScope override + pumpWidget 패턴
testWidgets('PriceText shows flash on price increase', (tester) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [...],
      child: MaterialApp(
        theme: AppTheme.dark,
        home: PriceText(price: 100000, previousPrice: 99000),
      ),
    ),
  );
  // 플래시 애니메이션 검증
  await tester.pump(const Duration(milliseconds: 150));
  // buyColor opacity 검증
});
```

---

## 10. 구현 파일 총 목록

### ST1: 공통 UI 컴포넌트 (18 신규 + 1 수정)

| 파일 | 역할 |
|------|------|
| `shared/widgets/price/price_text.dart` | 실시간 가격 + 플래시 |
| `shared/widgets/price/change_rate_text.dart` | 등락률 |
| `shared/widgets/price/pnl_text.dart` | 손익 텍스트 |
| `shared/widgets/loading/shimmer_box.dart` | Shimmer 로딩 스켈레톤 (단순 박스) |
| `shared/widgets/loading/shimmer_list.dart` | 리스트 스켈레톤 (CoinListTile 형태) |
| `shared/widgets/loading/loading_overlay.dart` | 전체화면 로딩 오버레이 |
| `shared/widgets/states/error_view.dart` | 에러 + 재시도 |
| `shared/widgets/states/empty_view.dart` | 빈 상태 |
| `shared/widgets/badges/ai_status_badge.dart` | AI 상태 배지 |
| `shared/widgets/badges/market_regime_chip.dart` | 장세 분류 칩 |
| `shared/widgets/badges/exchange_chip.dart` | 거래소 칩 |
| `shared/widgets/badges/order_side_badge.dart` | 매수/매도 뱃지 |
| `shared/widgets/connection/ws_connection_banner.dart` | WS 재연결/끊김 상단 배너 |
| `shared/widgets/coin_icon.dart` | 코인 아이콘 |
| `shared/widgets/coin_list_tile.dart` | 코인 목록 행 |
| `shared/widgets/order_button.dart` | 매수/매도 버튼 |
| `shared/widgets/trade_history_tile.dart` | 매매 내역 행 |
| `shared/widgets/app_search_bar.dart` | 공통 검색바 |
| `shared/widgets/confirm_bottom_sheet.dart` | 확인 바텀시트 |
| `pubspec.yaml` | 의존성 추가 (shimmer, cached_network_image, flutter_svg) |

### ST2: 스플래시 (1 수정)

| 파일 | 역할 |
|------|------|
| `features/auth/screens/splash_screen.dart` | 스플래시 UI |

### ST3: 로그인/회원가입 (4 수정 + 3 신규)

| 파일 | 역할 |
|------|------|
| `features/auth/screens/login_screen.dart` | 로그인 UI |
| `features/auth/screens/register_screen.dart` | 회원가입 UI |
| `features/auth/screens/forgot_password_screen.dart` | 비밀번호 찾기 UI |
| `features/auth/screens/email_verify_screen.dart` | 이메일 인증 UI |
| `features/auth/widgets/auth_header.dart` | 로고 + 환영 메시지 |
| `features/auth/widgets/social_login_buttons.dart` | 소셜 로그인 버튼 |
| `features/auth/widgets/password_field.dart` | 비밀번호 입력 필드 |

### ST4: 메인/홈 (1 수정 + 4 신규)

| 파일 | 역할 |
|------|------|
| `features/home/screens/home_screen.dart` | 홈 UI |
| `features/home/widgets/exchange_tab_bar.dart` | 거래소 탭 |
| `features/home/widgets/coin_search_delegate.dart` | 검색 로직 |
| `core/providers/market_state_provider.dart` | SelectedExchange/SelectedMarket (keepAlive, 교차 feature) |
| `core/utils/format_utils.dart` | 가격/등락률/수량 포맷 유틸 |

### ST5: 트레이딩 (1 수정 + 8 신규 + 1 에셋)

| 파일 | 역할 |
|------|------|
| `features/trading/screens/trading_screen.dart` | 트레이딩 UI (TradingScreen + TradingDetailScreen) |
| `features/trading/widgets/trading_header.dart` | 현재가 + 등락률 헤더 |
| `features/trading/widgets/chart/trading_view_chart.dart` | TradingView WebView 래퍼 |
| `features/trading/widgets/chart/timeframe_chips.dart` | 시간봉 선택 칩 |
| `features/trading/widgets/orderbook/orderbook_widget.dart` | 호가창 전체 |
| `features/trading/widgets/orderbook/orderbook_row.dart` | 호가창 행 |
| `features/trading/widgets/order/order_form.dart` | 주문 폼 전체 |
| `features/trading/widgets/order/balance_ratio_chips.dart` | 잔고 비율 칩 |
| `features/trading/providers/order_form_provider.dart` | 주문 폼 상태 |
| `assets/html/trading_view.html` | TradingView Lightweight Charts HTML |
| `assets/html/lightweight-charts.standalone.production.js` | Lightweight Charts JS 라이브러리 (로컬 번들) |

> **pubspec.yaml assets 섹션 추가**: `- assets/html/` (trading_view.html + JS 파일 포함)

### ST6: 거래소 설정 (1 수정 + 3 신규)

| 파일 | 역할 |
|------|------|
| `features/exchange/screens/exchange_screen.dart` | 거래소 설정 UI |
| `features/exchange/widgets/exchange_account_card.dart` | 거래소 카드 |
| `features/exchange/widgets/add_exchange_bottom_sheet.dart` | API 키 등록 |
| `features/exchange/widgets/security_info_card.dart` | 보안 안내 |

### ST7: AI 매매 대시보드 (1 수정 + 6 신규)

| 파일 | 역할 |
|------|------|
| `features/ai_trading/screens/ai_trading_screen.dart` | AI 대시보드 UI |
| `features/ai_trading/widgets/ai_master_switch.dart` | 전체 ON/OFF |
| `features/ai_trading/widgets/regime_summary_card.dart` | 장세 요약 |
| `features/ai_trading/widgets/daily_pnl_card.dart` | 오늘 손익 |
| `features/ai_trading/widgets/coin_ai_setting_tile.dart` | 코인별 AI 설정 |
| `features/ai_trading/widgets/ai_trade_log_tile.dart` | AI 매매 로그 |
| `features/ai_trading/providers/ai_master_switch_provider.dart` | 마스터 스위치 상태 |

### ST8: 포트폴리오 + 매매 내역 (2 수정 + 7 신규)

| 파일 | 역할 |
|------|------|
| `features/portfolio/screens/portfolio_screen.dart` | 포트폴리오 UI |
| `features/portfolio/widgets/total_asset_card.dart` | 총 자산 카드 |
| `features/portfolio/widgets/exchange_portfolio_section.dart` | 거래소별 자산 |
| `features/portfolio/widgets/coin_holding_tile.dart` | 보유 코인 행 |
| `features/portfolio/widgets/portfolio_pie_chart.dart` | 파이 차트 |
| `features/history/screens/history_screen.dart` | 매매 내역 UI |
| `features/history/widgets/history_summary_card.dart` | 요약 카드 |
| `features/history/widgets/history_filter_chips.dart` | 기간 필터 |
| `features/history/widgets/date_group_header.dart` | 날짜 그룹 |

### ST9: 프로필 수정 (1 수정 + 2 신규)

| 파일 | 역할 |
|------|------|
| `features/settings/screens/profile_screen.dart` | 프로필 수정 UI |
| `features/settings/widgets/avatar_picker.dart` | 아바타 선택 |
| `features/settings/providers/profile_edit_provider.dart` | 프로필 폼 상태 |

### ST10: 설정 (2 수정 + 2 신규)

| 파일 | 역할 |
|------|------|
| `features/settings/screens/settings_screen.dart` | 설정 UI |
| `features/settings/screens/more_screen.dart` | 더보기 메뉴 (i18n 적용) |
| `features/settings/widgets/settings_section.dart` | 설정 섹션 |
| `features/settings/widgets/settings_tile.dart` | 설정 행 |

### 전체 요약

| | 수정 파일 | 신규 파일 | 에셋 |
|---|----------|----------|------|
| ST1 | 1 | 19 | - |
| ST2 | 1 | - | 1 (logo.svg) |
| ST3 | 4 | 3 | - |
| ST4 | 1 | 4 | - |
| ST5 | 1 | 8 | 2 (trading_view.html + lightweight-charts.js) |
| ST6 | 1 | 3 | - |
| ST7 | 1 | 6 | - |
| ST8 | 2 | 7 | - |
| ST9 | 1 | 2 | - |
| ST10 | 2 | 2 | - |
| **합계** | **15** | **54** | **3** |

---

## 11. 구현 순서 및 의존성

```
ST1 (공통 UI 컴포넌트) ─────────────────────────────┐
                                                      │
ST1 완료 후 병렬 가능:                                  │
├── ST2 (스플래시) ──────────────────────────────────┤
├── ST3 (로그인/회원가입) ───────────────────────────┤
├── ST4 (홈) ───────────────────────────────────────┤
├── ST5 (트레이딩) ─────────────────────────────────┤
├── ST6 (거래소 설정) ──────────────────────────────┤
├── ST7 (AI 대시보드) ──────────────────────────────┤
├── ST8 (포트폴리오/내역) ──────────────────────────┤
├── ST9 (프로필) ───────────────────────────────────┤
└── ST10 (설정) ────────────────────────────────────┘
```

**ST1 선행 필수**: 모든 화면이 공통 위젯(PriceText, AsyncValueWidget, ShimmerPlaceholder 등)에 의존
**ST2~ST10 병렬 가능**: 각 화면은 독립적이며 서로 의존하지 않음

---

## 12. 기술 결정 요약

| 결정 | 선택 | 대안 | 근거 |
|------|------|------|------|
| 공통 위젯 구조 | `shared/widgets/` 카테고리별 서브폴더 | flat 구조 | 20개 수준에서 서브폴더가 가독성 향상 (code-architect 합의) |
| Feature 전용 위젯 | `features/{name}/widgets/` (trading은 서브폴더 허용) | 모두 shared | 2개 이상 feature 공유만 shared, 단일 feature 전용은 해당 feature 내 |
| UI 로컬 상태 | StatefulWidget (TabController, TextEditingController) | 모두 Riverpod | 화면 내부 전용 상태는 로컬이 자연스러움, 화면 이탈 시 초기화 의도적 |
| 데이터 상태 | AsyncValue + `.when()` 패턴 | 수동 loading/error 플래그 | Riverpod 표준 패턴, ErrorView/ShimmerList 공통 위젯 조합 |
| 교차 feature 상태 | core/providers/ keepAlive: true | feature 내 provider | 홈→트레이딩 거래소/코인 선택 유지 필요 (code-architect 제안) |
| 차트 메인 | TradingView Lightweight Charts (로컬 HTML WebView) | fl_chart, 외부 URL | 로컬 asset으로 네트워크 의존성/CSP 이슈 제거, 지표 오버레이 지원 |
| 차트 미니 | fl_chart (LineChart, PieChart) | custom paint | pubspec.yaml 이미 설치, 간단한 요약 차트에 적합 |
| 로딩 UI | Shimmer (shimmer_box + shimmer_list) | CircularProgressIndicator | design-concept.md 명시, 모던 UX 패턴 |
| 확인 다이얼로그 | BottomSheet (모바일 UX) | AlertDialog | 모바일 우선, 주문 확인 등 중요 액션에 적합 |
| 가격 포맷 | intl NumberFormat (FormatUtils) | number_formatter 패키지 | 이미 설치된 intl 활용, 추가 의존성 불필요 |
| 코인 아이콘 | CachedNetworkImage + fallback | 로컬 에셋만 | 거래소별 코인 아이콘 URL 동적 로드 필요 |
| SVG | flutter_svg | 래스터 이미지 | 로고/아이콘 해상도 독립적 렌더링 |
| WS 연결 상태 | 상단 배너 (ws_connection_banner) | 앱바 아이콘 | 재연결/끊김 상태를 명확히 전달, 코인원/업비트 레퍼런스 |
