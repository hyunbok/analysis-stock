# CoinTrader - 크로스플랫폼 코인 트레이딩 앱 PRD

## 1. 개요

Flutter 크로스플랫폼 코인 트레이딩 애플리케이션.
실시간 시세 조회, 호가창 거래, AI 기반 자동매매를 핵심 기능으로 제공한다.

- 단일 코드베이스로 iOS, Android, Windows, macOS, Web 지원
- 국내/해외 주요 거래소 통합 연동 (Exchange Abstraction Layer)
- AI 기반 자동매매 시스템 (OpenAI GPT + 기술적 지표)
- 실시간 차트 및 호가창 기반 수동 거래

---

## 2. 기술 스택

### 2.1 서버 (Backend)

| 항목 | 기술 |
|------|------|
| 언어 | Python 3.12+ |
| 프레임워크 | FastAPI (async) |
| 관계형 DB | PostgreSQL 16 + SQLAlchemy 2.0 (async) — 회원, 주문, 거래소 계정 등 트랜잭션 데이터 |
| 문서형 DB | MongoDB 7 + Beanie (async ODM) — AI 매매 로그, 시세/캔들, 뉴스 등 비정형 데이터 |
| 캐시/큐 | Redis 7 (캐시, Celery 브로커, Pub/Sub, Rate Limit) |
| 마이그레이션 | Alembic (PostgreSQL) / Beanie 마이그레이션 (MongoDB) |
| 인증 | JWT (access 30분 + refresh 14일), 이메일 비밀번호 재설정, 소셜 로그인(Google/Apple OAuth2) |
| 파일 스토리지 | S3 호환 스토리지 (프로필 아바타 이미지) |
| 실시간 | WebSocket (단일 연결 + 구독 메시지 방식) |
| 비동기 작업 | Celery + Redis (AI 매매, 뉴스 스크랩) |
| AI | OpenAI GPT API (모델은 환경변수 `OPENAI_MODEL`로 관리) |
| 컨테이너 | Docker + Docker Compose |

### 2.2 클라이언트 (Frontend)

| 항목 | 기술 |
|------|------|
| 프레임워크 | Flutter 3.x (Dart) |
| 상태관리 | Riverpod 2.x |
| 차트 | TradingView Lightweight Charts (WebView) |
| HTTP | Dio |
| WebSocket | web_socket_channel |
| 로컬 저장 | SharedPreferences / Hive |
| 다국어 | flutter_localizations + intl (ko, en, ja, zh, es) |
| 테마 | Material 3 (Light / Dark) |

### 2.3 지원 플랫폼 & UI 전략

**모바일 우선 (Mobile First)**
- Phase 1: iOS 15.0+ / Android API 26+ (모바일 UI 완성)
- Phase 2: Web (Chrome, Safari, Edge 최신 2버전) + Windows 10+ / macOS 12.0+ (반응형 확장)

> Flutter 단일 코드베이스로 전 플랫폼 빌드. 데스크톱/웹은 Phase 2에서 반응형 레이아웃 적용 (트레이딩 화면 가로 배치 등)

---

## 3. 시스템 아키텍처

```
┌──────────────────────────────────────────────────────────┐
│                    Flutter Client                          │
│   (iOS / Android / Windows / macOS / Web)                  │
└────────────┬────────────────────────┬─────────────────────┘
             │ REST API (HTTPS)       │ WebSocket (WSS)
┌────────────▼────────────────────────▼─────────────────────┐
│                    FastAPI Server                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │  Auth    │  │ Trading  │  │ AI Engine│  │ WS Hub    │ │
│  │ Service  │  │ Service  │  │ Service  │  │(Pub/Sub)  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘ │
│       │              │              │               │       │
│  ┌────▼──────────────▼──────────────▼───────────────┤       │
│  │         Exchange Abstraction Layer               │       │
│  │  ┌────────┐ ┌────────┐ ┌──────────┐ ┌────────┐  │       │
│  │  │ Upbit  │ │CoinOne │ │Coinbase  │ │Binance │  │       │
│  │  └────────┘ └────────┘ └──────────┘ └────────┘  │       │
│  └──────────────────────────────────────────────────┘       │
└──────┬──────────────┬──────────────┬───────────────────────┘
       │              │              │
  ┌────▼────┐  ┌────▼────┐  ┌────▼────┐  ┌──────────┐  ┌──────────┐
  │PostgreSQL│  │ MongoDB │  │  Redis  │  │ OpenAI   │  │  Celery  │
  │(트랜잭션)│  │(AI/시세) │  │Cache/Sub│  │  API     │  │  Worker  │
  └─────────┘  └─────────┘  └─────────┘  └──────────┘  └──────────┘

  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │  FCM/    │  │  File    │  │  OAuth   │
  │  APNs    │  │ Storage  │  │ Provider │
  │(푸시알림) │  │(S3/아바타)│  │(Google/  │
  └──────────┘  └──────────┘  │ Apple)   │
                              └──────────┘
```

### 3.1 핵심 설계 원칙

- **Exchange Abstraction Layer**: 모든 거래소를 공통 인터페이스(ABC)로 추상화, Provider Factory로 런타임 선택
- **비동기 우선**: FastAPI async/await, I/O 바운드 최적화
- **이벤트 기반 실시간**: Redis Pub/Sub → WS Hub → 클라이언트 브로드캐스트
- **관심사 분리**: API → Service → Repository 3계층 패턴
- **Celery Worker 분리**: AI 매매, 뉴스 스크랩 등 무거운 작업은 별도 워커에서 실행

### 3.2 핵심 데이터 흐름

```
실시간 시세:  Exchange WS → Provider → Redis Pub/Sub → WS Hub → Client
AI 자동매매: Celery Beat(5분) → 장세분석 → 전략선택 → 매매실행 → Exchange API → PostgreSQL(주문) + MongoDB(로그)
인증 흐름:   Login → JWT(access+refresh) → Redis refresh 저장 → WS 연결 시 토큰 검증
```

---

## 4. 데이터베이스

### 4.1 하이브리드 DB 전략

트랜잭션 정합성이 필요한 핵심 거래 데이터는 **PostgreSQL**, 비정형/대량 시계열 데이터는 **MongoDB**로 분리한다.

### 4.2 PostgreSQL (트랜잭션 데이터)

```
users ──< clients (디바이스)
  │
  ├──< user_social_accounts (소셜 로그인)
  │
  ├──< user_exchange_accounts ──< watchlist_coins
  │                                     │
  │                                     ▼
  │                            ai_trading_configs
  │
  └──< trade_orders
```

| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| users | 회원 | email, password_hash(NULL 허용—소셜 전용 계정), nickname, avatar_url, language, theme, price_color_style(korean/global), ai_trading_enabled, totp_secret(nullable), is_2fa_enabled, email_verified_at |
| user_social_accounts | 소셜 로그인 연동 | user_id(FK), provider(google/apple), provider_id, provider_email |
| clients | 클라이언트/디바이스 | user_id, device_type, fcm_token |
| user_exchange_accounts | 거래소 계정 | user_id, exchange_type, api_key_encrypted, api_secret_encrypted |
| coins | 코인 마스터 | symbol, name_ko, name_en, exchange_type, market_code |
| watchlist_coins | 관심 코인 | user_id, coin_id, exchange_account_id, sort_order |
| ai_trading_configs | AI 매매 설정 | watchlist_coin_id, is_enabled, max_investment_ratio(NUMERIC, 기본 0.10), stop_loss_ratio(NUMERIC, 기본 0.02), take_profit_ratio(NUMERIC, 기본 0.03), daily_max_loss_ratio(NUMERIC, 기본 0.05), primary_timeframe(VARCHAR, 기본 '5m'), confirmation_timeframes(VARCHAR[], 기본 '{"15m","1h"}'), strategy_params(JSONB — 장세별 전략 파라미터), enabled_at, disabled_at, disable_reason |
| ai_trading_config_history | AI 설정 변경 이력 | config_id(FK), action(enabled/disabled/params_updated), changed_by(user/system), change_detail(JSONB — 변경 전 파라미터 스냅샷) |
| trade_orders | 매매 주문 | order_type(buy/sell), order_method(market/limit), price, quantity, fee, status(pending/filled/cancelled/partial), is_ai_order |
| backtest_runs (M9) | 백테스팅 실행 이력 | user_id, coin_symbol, exchange_type, timeframe, start_date, end_date, initial_capital, strategy_config(JSONB), risk 파라미터 스냅샷, status(pending/running/completed/failed), celery_task_id |
| price_alerts | 가격 알림 조건 | user_id, coin_id, exchange_account_id, condition(above/below), target_price, is_triggered, is_active |
| user_consents | 개인정보 동의 이력 | user_id, consent_type(terms/privacy/marketing), agreed_at, version |

### 4.3 MongoDB (비정형/시계열 데이터)

| 컬렉션 | 설명 | 주요 필드 |
|--------|------|-----------|
| trade_logs | AI 매매 로그 | user_id, trade_order_id(PG 참조), coin_symbol, market_code, exchange_type, order_type/method, price/quantity/fee(비정규화 스냅샷), is_ai_order, market_regime, strategy_name, ai_decision_id, reasoning_summary, strategy_params_snapshot(JSONB), entry_price, pnl_amount/pnl_ratio/holding_minutes(청산 시 업데이트), status |
| ai_decisions | AI 판단 이력 | user_id, coin_symbol, market_regime, regime_confidence(dict), selected_strategy, action(buy/sell/hold), action_confidence, indicators_snapshot(IndicatorsSnapshot 내장 도큐먼트 — MA/EMA/VWAP/RSI/MACD/BB/ADX 등 14종 지표 스냅샷), gpt_model/gpt_prompt_tokens/gpt_completion_tokens/gpt_raw_response/gpt_parsed_result, news_context_summary, trade_log_id, execution_skipped_reason, analysis_duration_ms, celery_task_id. TTL 6개월 |
| daily_pnl_reports | 일별 손익 리포트 | user_id, report_date, total_pnl/trade_count/win_rate, ai_pnl/ai_trade_count/ai_win_count(AI 분리), manual_pnl/manual_trade_count(수동 분리), regime_stats(장세별 성과 dict), strategy_stats(전략별 성과 dict), cumulative_pnl. upsert 멱등성 보장 |
| candle_data_{tf} | 캔들/시세 히스토리 | 타임프레임별 별도 컬렉션 분리 (`candle_data_1m`~`candle_data_1d`). Time Series 컬렉션(timeField=timestamp, metaField=exchange_type+market_code). TTL 차등: 1m=7일, 5m=90일, 15m=180일, 1h=1년, 4h=2년, 1d=5년 |
| backtest_results (M9) | 백테스팅 결과 | backtest_run_id(PG 참조), summary(총수익률/승률/샤프비율/MDD), trades(개별 거래 임베딩), daily_performance(일별 성과), regime_performance(장세별 성과) |
| news_data | 뉴스 스크랩 | 비정형 텍스트, 임베딩 벡터 |
| notifications (M9) | 알림 이력 | user_id, type(price_alert/ai_trading/order_execution), title, body, data(가변 메타), is_read, TTL 90일 자동 만료 |
| audit_logs | 감사 로그 | user_id, action(login/logout/api_key_change/password_change/2fa_toggle), ip_address, user_agent, details(가변), created_at |

### 4.4 크로스DB 설계 주의사항

- **trade_logs(Mongo) → trade_orders(PG) 참조**: DB 레벨 조인 불가. trade_logs에 order 스냅샷(price, quantity, order_type) 비정규화 저장
- **daily_pnl_reports 집계**: PG(trade_orders) + Mongo(trade_logs) 동시 조회 필요. `report_date + user_id` 기준 upsert로 멱등성 보장
- **Beanie Document → API 응답**: `_id`, `revision_id` 등 내부 필드 노출 방지. `ResponseSchema.model_validate(document)` 변환 패턴 사용

> 상세 스키마(컬럼 타입, 인덱스, 제약조건, 도큐먼트 구조)는 DB 설계 태스크에서 정의한다.

### 4.5 Redis 활용

| 용도 | 키 패턴 |
|------|---------|
| Refresh Token | `auth:refresh:{user_id}:{client_id}` |
| Rate Limiting | `rate:{ip}`, `rate:{user_id}` |
| 실시간 시세 Pub/Sub | `ticker:{exchange}:{market}` |
| 알림 미읽 수 캐시 | `notifications:unread_count:{user_id}` |
| 기술적 지표 스냅샷 | `indicators:{exchange}:{market}:{timeframe}` (TTL 60~600s, 타임프레임별 차등) |
| 장세 분석 결과 | `regime:{exchange}:{market}` (TTL 300s, Celery 분석 완료 시 갱신) |
| AI 최신 결정 | `ai_decision:{user_id}:{market}:latest` (TTL 300s) |
| 캔들 캐시 | `candles:{exchange}:{market}:{timeframe}:{count}` (TTL 30s, Cache-Aside 패턴) |
| GPT 뉴스 감성 캐시 | `ai:news_sentiment:{coin}` (TTL 30분) |
| 마지막 분석 시간 | `ai:last_run:{user_id}:{coin}` (TTL 10분) |
| AI 실시간 신호 Pub/Sub | `ai:signal:{user_id}` (매매 신호 발행) |
| Celery 브로커/결과 | Celery 기본 설정 |

---

## 5. API 설계

### 5.1 REST API

| 그룹 | 주요 엔드포인트 |
|------|----------------|
| 인증 | `POST /api/v1/auth/register, login, refresh, logout` / `POST /api/v1/auth/forgot-password, reset-password` / `GET,PUT /api/v1/auth/me` / `POST,DELETE /api/v1/auth/me/avatar` / `DELETE /api/v1/auth/me` (계정 삭제) |
| 소셜 인증 | `POST /api/v1/auth/social/google` / `POST /api/v1/auth/social/apple` |
| 클라이언트 | `POST,GET /api/v1/clients` / `DELETE /api/v1/clients/{id}` |
| 거래소 계정 | `POST,GET /api/v1/exchanges` / `PUT,DELETE /api/v1/exchanges/{id}` / `POST .../verify` |
| 코인 | `GET /api/v1/coins?q={keyword}` / `GET /api/v1/coins/{id}` |
| 관심 코인 | `GET,POST /api/v1/watchlist` / `DELETE /api/v1/watchlist/{id}` / `PUT .../reorder` |
| 주문 | `POST,GET /api/v1/orders` / `GET,DELETE /api/v1/orders/{id}` / `GET /api/v1/orders?status=open` / `POST /api/v1/orders/batch-cancel` |
| 자산 | `GET /api/v1/portfolio` (전체 자산 요약) / `GET /api/v1/portfolio/{exchange_id}` (거래소별 상세) |
| AI 매매 | `POST,GET /api/v1/ai-trading/configs` / `PUT .../configs/{id}` / `PATCH .../configs/{id}/activation` / `PATCH /api/v1/ai-trading/master-switch` |
| AI 통계 | `GET /api/v1/ai-trading/logs` / `GET .../stats/daily` / `GET .../stats/total` |
| AI 백테스팅 (M9) | `POST /api/v1/ai-trading/backtest` (비동기 실행, 202 + task_id) / `GET .../backtest/{task_id}` (결과 폴링) |
| 가격 알림 | `POST,GET /api/v1/price-alerts` / `DELETE /api/v1/price-alerts/{id}` |
| 알림 (M9) | `GET /api/v1/notifications` / `PATCH /api/v1/notifications/{id}/read` / `POST /api/v1/notifications/mark-all-read` / `GET /api/v1/notifications/unread-count` / `DELETE /api/v1/notifications/{id}` / `PUT /api/v1/notifications/settings` |
| 2FA | `POST /api/v1/auth/2fa/setup` (TOTP QR 생성) / `POST /api/v1/auth/2fa/verify` (활성화 확인) / `POST /api/v1/auth/2fa/disable` |
| 세션 관리 | `GET /api/v1/auth/sessions` (활성 세션 목록) / `DELETE /api/v1/auth/sessions/{client_id}` (세션 강제 종료) / `POST /api/v1/auth/logout-all` |
| 앱 버전 | `GET /api/v1/app-version` (최소 지원 버전, 강제 업데이트 여부) |
| 헬스체크 | `GET /health` |

### 5.2 WebSocket

단일 연결 + 구독 메시지 방식으로 설계한다.

```
연결: ws://.../ws/v1?token={access_token}

구독 요청: { "action": "subscribe", "channel": "ticker", "exchange": "upbit", "market": "KRW-BTC" }
구독 해제: { "action": "unsubscribe", "channel": "ticker", "exchange": "upbit", "market": "KRW-BTC" }

채널 종류: ticker(시세), orderbook(호가), trades(체결), my-orders(내 주문)

연결 상태 UI: 연결됨(녹색), 연결 중(황색+스피너), 연결 끊김(적색+"재연결 중" 배너)
```

> 상세 요청/응답 스키마는 구현 태스크에서 정의한다.

---

## 6. 거래소 연동

### 6.1 지원 거래소

| 거래소 | 구분 | 기축 통화 | Phase |
|--------|------|-----------|-------|
| Upbit | 국내 | KRW | Phase 1 |
| CoinOne | 국내 | KRW | Phase 1 |
| Coinbase | 해외 | USD | Phase 2 |
| Binance | 해외 | USDT | Phase 2 |

### 6.2 Exchange Abstraction Layer

```python
# REST 조회/주문
class ExchangeRestProvider(ABC):
    async def get_ticker(market) -> Ticker
    async def get_orderbook(market) -> OrderBook
    async def get_candles(market, interval, count) -> list[Candle]
    async def place_order(order) -> OrderResult       # order_method: market/limit
    async def cancel_order(order_id) -> bool
    async def get_balance() -> list[Balance]
    async def get_trading_fee(market) -> TradingFee   # maker/taker 수수료율
    async def verify_api_key() -> ApiKeyInfo           # 권한 범위 확인 (trade/withdraw 등)

# 실시간 스트리밍
class ExchangeStreamProvider(ABC):
    async def subscribe_ticker(markets, callback) -> None
    async def subscribe_orderbook(markets, callback) -> None

# 통합 프로바이더
class ExchangeProvider(ExchangeRestProvider, ExchangeStreamProvider):
    pass

# 팩토리
class ExchangeProviderFactory:
    def create(exchange_type, credentials) -> ExchangeProvider
```

### 6.3 거래소 API 키 권한 검증

API 키 등록(`POST /api/v1/exchanges`) 시 `verify_api_key()`로 권한 범위를 확인한다.
- **출금 권한 감지 시**: "출금 권한이 포함된 API 키입니다. 보안을 위해 출금 권한 없는 키 사용을 권장합니다." 경고 표시
- **조회 전용 키**: 정상 등록, 주문 기능 비활성화 안내
- **거래 권한 키**: 정상 등록 (권장)
- **출금 포함 키**: 경고 후 사용자 확인 시 등록 허용

### 6.4 Circuit Breaker (거래소 장애 대응)

거래소 API 호출에 Circuit Breaker 패턴을 적용하여 장애 전파를 방지한다.
- **Closed (정상)**: 요청 통과, 실패율 모니터링
- **Open (차단)**: 연속 5회 실패 또는 30초 내 실패율 50% 초과 시 → 요청 즉시 실패 반환, 사용자에게 "거래소 연결 불안정" 알림
- **Half-Open (복구 시도)**: 30초 후 1건 테스트 요청 → 성공 시 Closed, 실패 시 Open 유지
- 거래소별 독립 Circuit Breaker 운영

### 6.5 거래소별 Rate Limiting

| 거래소 | REST API 한도 | WebSocket 한도 |
|--------|-------------|---------------|
| Upbit | 초당 10회 (주문), 분당 600회 (조회) | 연결당 15개 마켓 구독 |
| CoinOne | 초당 10회 | 연결당 구독 제한 없음 |
| Coinbase | 분당 10,000회 | - |
| Binance | 분당 1,200회 (Weight 기반) | 연결당 200개 스트림 |

서버 측에서 거래소별 Rate Limiter를 운영하여 한도 초과 방지. Token Bucket 알고리즘 사용.

### 6.6 거래소 인증

| 거래소 | 인증 방식 |
|--------|-----------|
| Upbit | JWT (access key + secret key 서명) |
| CoinOne | HMAC-SHA512 |
| Coinbase | API Key + HMAC-SHA256 |
| Binance | API Key + HMAC-SHA256 query string |

### 6.7 개발자 문서

- Upbit: https://docs.upbit.com/kr/reference/api-overview
- CoinOne: https://docs.coinone.co.kr/reference/range-unit
- Coinbase: https://docs.cdp.coinbase.com/api-reference/v2/introduction
- Binance: https://www.binance.com/en/binance-api

---

## 7. AI 자동매매 시스템

### 7.1 전체 흐름

5단계 파이프라인으로 구성된다.

```
Celery Beat (5분 주기)
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 1: 데이터 수집 (Data Collection)                       │
    │  - 거래소 API: 2일치 5분봉 캔들 (~576개)                       │
    │  - 거래소 API: 현재 호가/틱 데이터                              │
    │  - MongoDB: 최근 뉴스 데이터 (news_data)                       │
    │  - Redis: 최근 실시간 시세 스냅샷                               │
    │  - PostgreSQL: 사용자 AI 설정 (ai_trading_configs)             │
    └──────────────────────┬──────────────────────────────────────┘
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 2: 전처리 및 지표 계산 (Preprocessing)                  │
    │  - 캔들 데이터 정규화 (거래소별 포맷 통일)                       │
    │  - 기술적 지표 계산 (11종): EMA, VWAP, RSI, MACD, BB, ADX,   │
    │    ATR, Stochastic, OBV, Williams %R, CCI                    │
    │  - 뉴스 감성 점수 산출 (GPT 또는 룰 기반)                       │
    │  - 결측값/이상치 필터링                                        │
    └──────────────────────┬──────────────────────────────────────┘
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 3: 장세 분석 (Market Regime Detection)                  │
    │  - 기술적 지표 기반 장세 1차 분류 (규칙 기반)                    │
    │  - GPT 보조 분석 (뉴스 + 지표 종합 판단)                        │
    │  - 최종 장세 결정: Trend / Range / Transition                  │
    │  - 각 장세별 confidence score(%) 산출                         │
    │  - MongoDB ai_decisions에 분석 결과 저장                       │
    └──────────────────────┬──────────────────────────────────────┘
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 4: 전략 선택 및 매매 결정 (Strategy & Decision)          │
    │  - 장세 → 전략 매핑 (confidence 임계값 기반)                    │
    │  - 선택된 전략의 진입/청산 조건 평가                             │
    │  - 리스크 관리 검증 (포지션 크기, 손절/익절, 일일 한도)            │
    │  - 매매 신호 생성: BUY / SELL / HOLD                          │
    │  - GPT 최종 검증 (선택적, 고위험 거래 시)                        │
    └──────────────────────┬──────────────────────────────────────┘
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 5: 주문 실행 및 기록 (Execution & Logging)              │
    │  - Exchange Abstraction Layer를 통한 주문 실행                  │
    │  - 주문 상태 추적 (filled/partial/failed)                      │
    │  - 예외 처리 (실패 시 재시도/스킵 판단)                          │
    │  - PostgreSQL: trade_orders 기록                              │
    │  - MongoDB: trade_logs (AI 판단 근거 포함) 기록                 │
    │  - 사용자 알림 (WS + 푸시)                                    │
    └─────────────────────────────────────────────────────────────┘
```

### 7.2 마스터 스위치

- users 테이블의 `ai_trading_enabled`로 전체 AI 매매 ON/OFF 제어
- OFF 시 모든 코인별 AI 매매 일괄 중지 (안전장치)
- 클라이언트: 다음 분석까지 카운트다운 타이머 표시 (마지막 분석 시간 + 5분 주기 기반)

### 7.3 장세 분석

- **입력**: 뉴스 데이터, 2일치 5분봉(~576캔들), 기술적 지표(EMA, VWAP, RSI, MACD, Bollinger Bands, ADX, ATR, Stochastic, OBV, Williams %R, CCI)
- **출력**: Trend(추세) / Range(횡보) / Transition(전환) 분류 + 각 장세별 confidence score(%) 포함

#### 7.3.1 기술적 지표 상세 명세

**1. 이동평균선 (EMA/SMA)**

```
SMA(n) = (P₁ + P₂ + ... + Pₙ) / n
EMA(t) = P(t) × k + EMA(t-1) × (1 - k),  k = 2 / (n + 1)
```

| 파라미터 | 기본값 | 용도 |
|---------|-------|------|
| EMA 20 | 20 | 단기 추세, 눌림목 기준선 |
| EMA 50 | 50 | 중기 지지/저항 |
| EMA 200 | 200 | 장기 추세 방향 |

- **매수 시그널**: EMA20 > EMA50 > EMA200 (정배열) + 가격 EMA20 위에서 반등
- **매도 시그널**: EMA20 < EMA50 < EMA200 (역배열) + 가격 EMA20 아래
- **골든/데드크로스**: EMA20-EMA50 교차
- **눌림목 매수**: 정배열 + EMA20 터치 후 반등 + 거래량 증가

> 5분봉에서는 SMA보다 최근 변화 반응이 빠른 EMA를 우선 사용

**2. VWAP (Volume Weighted Average Price)**

```
VWAP = Σ(Typical Price × Volume) / Σ(Volume)
Typical Price = (High + Low + Close) / 3
밴드: VWAP ± (k × σ),  k = 1.5 (기본)
```

- 당일 KST 00:00 기준 리셋
- **매수**: VWAP 아래→위 돌파 + 거래량 증가, 상승 추세 중 VWAP 터치 반등
- **매도**: VWAP 위→아래 돌파, 하락 추세 중 VWAP 터치 반락
- **반전**: 밴드 경계 터치 + 반전 캔들

**3. RSI (Relative Strength Index)**

```
RSI = 100 - (100 / (1 + RS))
RS = Average Gain / Average Loss (14기간 EMA 방식)
```

| 파라미터 | 기본값 | 조정 범위 |
|---------|-------|----------|
| 기간 | 14 | 9~21 |
| 과매수 | 70 | 65~80 |
| 과매도 | 30 | 20~35 |

- **다이버전스 탐지**: 최근 20~50캔들 내 가격-RSI 저점/고점 비교 (Bullish: 가격↓ RSI↑, Bearish: 가격↑ RSI↓)
- 다이버전스 유효 조건: 저점/고점 간격 5캔들 이상

**4. MACD (Moving Average Convergence Divergence)**

```
MACD Line = EMA(12) - EMA(26)
Signal Line = EMA(9) of MACD Line
Histogram = MACD Line - Signal Line
```

- **매수**: Golden Cross (MACD > Signal) + 히스토그램 양전환
- **매도**: Dead Cross (MACD < Signal) + 히스토그램 음전환
- **모멘텀 약화**: 히스토그램 연속 감소 3봉 이상

**5. Bollinger Bands (볼린저 밴드)**

```
Middle = SMA(20), Upper/Lower = SMA(20) ± (2 × σ)
%B = (Price - Lower) / (Upper - Lower)
Bandwidth = (Upper - Lower) / Middle
```

- **매수**: 하단밴드 터치 + %B < 0.05 + 반전 캔들
- **매도**: 상단밴드 터치 + %B > 0.95 + 반전 캔들
- **스퀴즈**: Bandwidth < 최근 6개월 최저의 120% → 횡보 신호

**6. ADX (Average Directional Index)**

```
+DI, -DI: 14기간 방향 지표
ADX = EMA(14) of DX,  DX = |+DI - (-DI)| / (+DI + (-DI)) × 100
```

- **강한 추세 (Trend)**: ADX > 25, 매우 강한 추세: ADX > 40
- **횡보 (Range)**: ADX < 20
- **추세 전환 영역**: ADX 20~25
- **DI 크로스**: +DI > -DI → 상승, -DI > +DI → 하락

#### 7.3.2 추가 지표

| 지표 | 공식 요약 | 기본 파라미터 | 도입 근거 |
|------|----------|-------------|----------|
| **ATR** (Average True Range) | EMA(14) of TR | 14기간 | 변동성 기반 동적 손절/익절 설정에 필수. 고정 비율보다 ATR 배수가 코인 시장에 적합 |
| **Stochastic** | %K = (Close-LowestLow)/(HighestHigh-LowestLow)×100, Slow %D = SMA(3) of %K | 14/3, 과매수 80, 과매도 20 | RSI 보완. Range 장세에서 단기 반전 포착에 더 민감 |
| **OBV** (On Balance Volume) | 양봉 시 +Volume, 음봉 시 -Volume 누적 | EMA 20 | 가격 변동의 거래량 뒷받침 확인. Transition 장세에서 추세 전환 진위 판별 |
| **Williams %R** | -100 × (HighestHigh - Close)/(HighestHigh - LowestLow) | 14, 과매수 -20, 과매도 -80 | RSI+볼밴 3중 조건 보완. Range 장세 보조 확인 |
| **CCI** (Commodity Channel Index) | (TP - SMA(TP)) / (0.015 × Mean Deviation) | 20, ±100 | VWAP 밴드 반전 보조. 극단값(±200) 시 급반전 가능성 |

#### 7.3.3 지표 조합 규칙 (복합 시그널 스코어링)

각 지표 시그널을 4개 카테고리로 분류하고 가중 합산하여 최종 스코어(-1.0 ~ +1.0) 산출:

| 카테고리 | 지표 | 가중치 |
|---------|------|-------|
| **추세 확인** (Trend) | EMA 배열 (2.0), ADX 강도 (1.5), VWAP 위치 (1.5) | - |
| **모멘텀** (Momentum) | MACD 크로스 (2.0), RSI (1.5), MACD 히스토그램 (1.0), Stochastic (1.0) | - |
| **반전** (Reversal) | RSI 다이버전스 (2.5), 반전 캔들 (2.0), BB 밴드 터치 (1.5), Williams %R (1.0) | - |
| **거래량** (Volume) | OBV 방향 (1.5), 거래량 급증 (1.0) | - |

**시그널 강도 분류:**

| 강도 | 스코어 범위 | 조건 |
|------|-----------|------|
| Strong Buy | > +0.6 | 주요 지표 3개 이상 매수 일치 |
| Medium Buy | +0.3 ~ +0.6 | 주요 지표 2개 매수 + 보조 확인 |
| Weak Buy | +0.1 ~ +0.3 | 단일 강한 지표 또는 복수 약한 지표 |
| Neutral | -0.1 ~ +0.1 | 혼재 또는 중립 |
| Weak~Strong Sell | -0.1 미만 | 매수의 반대 조건 |

#### 7.3.4 장세 분류 알고리즘

1차 분류는 규칙 기반, GPT가 보조 검증한다.

**규칙 기반 분류 조건:**

| 장세 | 조건 (AND) |
|------|-----------|
| **Trend** | ADX > 25 AND (EMA 정/역배열 OR MACD 히스토그램 연속 증가/감소 3봉 이상) |
| **Range** | ADX < 20 AND BB Bandwidth < 임계값 AND RSI 40~60 |
| **Transition** | RSI 다이버전스 감지 OR MACD 크로스오버 임박 OR ADX 20~25 급변 |

**가중치 기반 Confidence Score 산출:**

```
ADX 기반(30%) + EMA 배열(20%) + MACD 크로스 임박(15%) + RSI 다이버전스(20%) + BB Bandwidth(15%)
→ 각 장세별 점수 산출 → softmax 정규화 → 최고점수 장세 선택
```

#### 7.3.5 장세 → 전략 연결 로직

```
confidence >= 70% → 해당 장세 전용 전략 실행 (풀 포지션)
50% <= confidence < 70% → 보수적 전략 (포지션 50% 축소)
confidence < 50% → HOLD (매매 보류, "장세 불확실" 로그 기록)
```

**Trend 장세 내 전략 선택:**

| 조건 | 선택 전략 |
|------|----------|
| EMA20-EMA60 정배열 + 가격 EMA20 근처 | TrendMA 눌림목 |
| VWAP 위 가격 + 거래량 평균 이상 | VWAP 눌림목 |
| 둘 다 충족 | TrendMA 우선 (더 보수적) |

**Range 장세 내 전략 선택:**

| 조건 | 선택 전략 |
|------|----------|
| BB 상/하단 터치 + RSI 과매수/과매도 | RSI+볼밴+반전캔들 |
| VWAP 밴드 상/하단 근접 | VWAP 밴드 반전 |
| 둘 다 충족 | RSI+볼밴+반전캔들 우선 (신호 더 강함) |

### 7.4 장세별 전략

| 장세 | 전략 | 핵심 |
|------|------|------|
| Trend | TrendMA 눌림목, VWAP 눌림목 | MA/VWAP 지지 반등 매매 |
| Range | VWAP 밴드 반전, RSI+볼밴+반전캔들 | 밴드 경계 반전 매매 |
| Transition | RSI 다이버전스 + MACD | 추세 전환 포착 |

#### 7.4.1 전략별 진입/청산 조건 상세

**전략 A: TrendMA 눌림목**

진입 조건 (매수):
1. EMA20 > EMA50 > EMA200 (정배열)
2. ADX > 25 (+DI > -DI)
3. 가격이 EMA20에 근접 (|가격 - EMA20| / EMA20 < 0.5%)
4. EMA20에서 반등 양봉
5. 거래량 >= 최근 20봉 평균 × 1.2
6. RSI 40~65 범위

청산: 익절 ATR×2.0 / 손절 EMA50 이탈 또는 ATR×1.5 / RR 1:2

**전략 B: VWAP 눌림목**

진입 조건 (매수):
1. 가격 > VWAP
2. ADX > 20
3. 가격이 VWAP ± 0.3% 터치
4. 반전 캔들 (해머, Bullish Engulfing)
5. RSI 40~65
6. OBV 상승 추세 유지

청산: 익절 VWAP 상단밴드(k=1.5) 또는 ATR×2.0 / 손절 VWAP-ATR×0.5 / RR 1:2

**전략 C: VWAP 밴드 반전**

진입 조건 (매수 - 하단밴드):
1. ADX < 20 (횡보)
2. BB Bandwidth 수축 상태
3. 가격이 VWAP 하단밴드(k=1.5) 터치
4. 반전 캔들 패턴
5. RSI < 40
6. %B < 0.1

청산: 익절 VWAP 중심선 / 손절 밴드 이탈 + ATR×0.5 / RR 1:1.5

**전략 D: RSI + 볼밴 + 반전캔들 3중 조건**

진입 조건 (매수 — 3조건 모두 동시 충족 필수):
- [조건 1] RSI(14) < 30 + Stochastic %K < 20
- [조건 2] 가격이 BB Lower Band 터치 + %B < 0.05
- [조건 3] 반전 캔들 (해머 / Bullish Engulfing / 도지 중 하나)

청산: 익절 BB Middle Band(SMA20) / 손절 BB 이탈 + ATR×1.0 / RR 1:1.5~2.0

**전략 E: RSI 다이버전스 + MACD 확정**

진입 조건 (Bullish):
1. RSI Bullish Divergence (최근 50캔들, 가격 저점↓ RSI 저점↑, 간격 5캔들 이상)
2. MACD Golden Cross + 히스토그램 음→양 전환 (다이버전스 이후 순서 중요)
3. ADX < 25 또는 감소 중 + OBV 상승 전환 시작

청산: 익절 ATR×2.5 / 손절 다이버전스 발생 저점 이탈 / RR 1:2.5

#### 7.4.2 반전 캔들 패턴 정의

| 패턴 | 판별 조건 |
|------|----------|
| **해머 (Hammer)** | 아래꼬리 >= 몸통×2, 위꼬리 <= 몸통×0.5, 몸통/전체범위 > 10% |
| **Bullish Engulfing** | 직전 음봉, 현재 양봉, 현재가 직전을 완전히 감싸는 패턴 |
| **Shooting Star** | 위꼬리 >= 몸통×2, 아래꼬리 <= 몸통×0.5 |
| **Bearish Engulfing** | 직전 양봉, 현재 음봉, 현재가 직전을 완전히 감싸는 패턴 |
| **도지 (Doji)** | 몸통 <= 전체범위의 10% |

### 7.5 리스크 관리

#### 7.5.1 기본 리스크 파라미터

| 항목 | 기본값 | 최소 | 최대 | 설명 |
|------|-------|-----|-----|------|
| 단일 거래 최대 손실 | 2% | 0.5% | 5% | 총 자산 대비 |
| 일일 최대 손실 | 5% | 1% | 10% | 당일 누적 |
| 총 최대 낙폭 (MDD) | 15% | 5% | 30% | 전체 기간 |
| 최대 동시 포지션 | 3 | 1 | 5 | 코인 수 |
| 최대 투자 비율 (단일) | 10% | 2% | 20% | 총 자산 대비 |
| 연속 손실 한도 | 3 | 1 | 5 | 연속 횟수 |

#### 7.5.2 포지션 사이징

**Fixed Fractional (기본)**:
```
투자 금액 = (총 자산 × 리스크 비율) / 손절 비율
예: (1,000만 × 2%) / 3% = 666만원,  최대 10% 캡 적용
```

**Half-Kelly (보조)**: Kelly % = W - (1-W)/R, Half-Kelly = Kelly × 0.5 (1%~10% 클램프)
- W: 최근 N회 승률, R: 평균 수익/손실 비율
- Fixed와 Kelly 중 더 보수적 값 채택
- Confidence/시그널 강도에 따라 추가 조정 (Strong: ×1.0, Medium: ×0.75, Weak: ×0.5)

#### 7.5.3 동적 손절/익절 (ATR 기반)

고정 비율 대신 전략별 ATR 배수 차등 적용:

| 전략 | 손절 (ATR 배수) | 익절 (ATR 배수) | RR |
|------|---------------|---------------|-----|
| TrendMA / VWAP 눌림목 | 1.5 | 3.0 | 1:2 |
| VWAP 밴드 / RSI+볼밴 | 1.0 | 1.5 | 1:1.5 |
| RSI 다이버전스+MACD | 1.5 | 3.75 | 1:2.5 |

**Trailing Stop**: 익절 목표 50% 도달 시 활성화, 트레일링 거리 ATR×1.0

#### 7.5.4 드로다운 관리

- **일일 손실 한도**: -5% 초과 시 당일 AI 매매 전체 중지
- **총 낙폭 한도**: -15% 초과 시 AI 매매 일시 정지
- **연속 손실**: 3회 연속 손실 시 4시간 쿨다운
- 한도 초과 시 사용자에게 FCM 푸시 알림

### 7.6 통계

- 매매 로그: 진입/청산 가격, 전략, AI 판단 근거
- 일별 통계: 거래 횟수, 승률, 총 손익, AI vs 수동 분리, 장세별/전략별 성과
- 누적 통계: 총 수익률, 샤프 비율, MDD, 최선/최악 거래, 전략별 성과

### 7.7 타임프레임별 지표 파라미터

| 타임프레임 | 역할 | 주요 지표 |
|-----------|------|----------|
| **5분봉** (Primary) | 메인 진입 타임프레임 | EMA 20/50/200, RSI 14, MACD 12/26/9, BB 20/2.0, ADX 14, ATR 14, Stochastic 14/3, VWAP |
| **15분봉** (Confirmation) | 5분봉 시그널 방향 확인 | EMA 20/50/200, RSI 14, MACD 12/26/9, ADX 14 |
| **1시간봉** (Trend) | 상위 추세 방향 | EMA 20/50, VWAP, RSI 21, ADX 14 |
| **4시간봉** (Major) | 주요 추세 방향 | EMA 50/200, RSI 21, MACD 12/26/9 |
| **일봉** (Context) | 시장 전체 강도 | SMA 50/200, RSI 21 |

**멀티 타임프레임(MTF) 분석 규칙:**
- 1시간봉, 4시간봉 모두 같은 방향 → 허용 (가중치 1.0)
- 한 타임프레임만 일치 → 허용 (가중치 0.75)
- 둘 다 반대 방향 → **차단** (Counter-Trend 거래 금지)
- 둘 다 neutral → 허용 (가중치 0.5, 포지션 축소)

### 7.8 Celery 워커-서버 통신 구조

#### 7.8.1 아키텍처

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│  FastAPI     │◄───────►│    Redis     │◄───────►│  Celery      │
│  Server      │         │  (Broker +   │         │  Worker      │
│  - REST API  │         │   Result +   │         │  - ai_trading│
│  - WS Hub    │         │   Pub/Sub)   │         │  - news_scrap│
│  - 주문 실행 │         │              │         │  - pnl_report│
└──────┬───────┘         └──────────────┘         └──────┬───────┘
       │                                                  │
       └──────────────►  PostgreSQL + MongoDB  ◄──────────┘
```

#### 7.8.2 통신 흐름

| 흐름 | 방향 | 메커니즘 |
|------|------|---------|
| 매매 주기 시작 | Beat → Worker | Redis Broker (5분 주기) |
| AI 분석 결과 전달 | Worker → Server | Redis Pub/Sub (`ai:signal:{user_id}`) |
| 주문 실행 | Worker → Exchange | Exchange Abstraction Layer 직접 호출 |
| 결과 알림 | Worker → Server → Client | Redis Pub/Sub → WS Hub → Client |
| 로그/통계 기록 | Worker → DB | PostgreSQL(주문) + MongoDB(로그) 직접 |
| 상태 조회 | Server → Worker | Celery AsyncResult / Redis 키 |

#### 7.8.3 Celery 태스크 설계

- **ai 큐**: AI 매매 전용 (`run_all_active_configs`, `run_single_config`, `run_backtest`)
- **scraper 큐**: 뉴스 스크랩 전용
- **default 큐**: 일별 리포트, 토큰 정리

**Beat 스케줄:**

| 태스크 | 주기 | 큐 |
|--------|------|-----|
| AI 매매 사이클 | 5분 (300초) | ai |
| 뉴스 스크랩 | 1시간 | scraper |
| 일별 PnL 리포트 | 매일 00:00 UTC | default |
| 만료 토큰 정리 | 매일 03:00 UTC | default |

**Worker 설정:**
- 동시성: `--concurrency=4` (CPU 코어 기반)
- 타임아웃: 전체 사이클 240초(soft)/300초(hard), 개별 코인 90초(soft)/120초(hard)
- 재시도: 개별 코인 최대 2회, exponential backoff (30초 기반)
- 에러 핸들링: GPT 폴백(규칙 기반만), Circuit Breaker 연동, DLQ, Sentry

### 7.9 주문 실행 예외 처리

#### 7.9.1 주문 상태 머신

```
PENDING → 거래소 API 호출 → FILLED (전량체결)
                           → PARTIAL → 60초 대기 → FILLED or PARTIAL_CANCELLED
                           → OPEN → 120초 대기 → FILLED or CANCELLED
       → API 실패 → RETRY (최대 2회, 30초 backoff) → FILLED or FAILED
```

#### 7.9.2 예외 처리 상세

| 예외 상황 | 처리 | 사용자 알림 |
|----------|------|-----------|
| 전량 체결 | 정상 완료, DB 기록 | 푸시: "BTC 매수 체결 완료" |
| 부분 체결 | 60초 대기 → 잔량 시장가 전환 또는 취소 | 푸시: "부분 체결 (70%), 잔량 취소" |
| 잔고 부족 | 해당 코인 1회 스킵, 다음 주기 재시도 | 대시보드 표시 |
| 네트워크 오류 | 30초 간격 최대 2회 재시도 | 3회 연속 실패 시 푸시 |
| Circuit Breaker Open | 해당 거래소 AI 매매 일시 중지 | 푸시: "거래소 연결 불안정" |
| 일일 손실 한도 초과 | 당일 AI 매매 전체 중지 | 푸시: "일일 손실 한도 도달" |

### 7.10 GPT 연동 상세

GPT는 **보조 분석 도구**로 활용하며, 최종 매매 결정은 규칙 기반 엔진이 수행한다.

#### 7.10.1 GPT 역할

| 역할 | 호출 시점 | 필수 여부 |
|------|----------|----------|
| 장세 검증 | Stage 3 (장세 분석) | 선택적 (confidence < 70% 또는 Transition 시) |
| 뉴스 감성 분석 | Stage 2 (전처리) | 선택적 |
| 매매 판단 보조 | Stage 4 (고위험 거래) | 선택적 |
| 일일 리포트 생성 | 일일 정산 시 | 선택적 |

#### 7.10.2 프롬프트 전략

- **장세 검증**: 기술적 지표 요약 + 뉴스 5건 + 규칙 기반 결과 → Trend/Range/Transition 판단 + 근거 3줄 → JSON 응답
- **뉴스 감성**: 헤드라인 목록 → positive/negative/neutral + score(-1.0~1.0) → JSON 응답

#### 7.10.3 호출 정책

| 항목 | 정책 |
|------|------|
| 모델 | 환경변수 `OPENAI_MODEL` (기본: gpt-4o-mini) |
| 타임아웃 | 30초 (초과 시 규칙 기반으로 진행) |
| 비용 제어 | 사용자당 일 50회 한도, 토큰 최대 2000/요청 |
| Fallback | GPT 응답 실패/파싱 오류 → 규칙 기반 결과만 사용 |
| 캐싱 | 뉴스 감성 30분 Redis 캐시 |
| 응답 검증 | JSON 파싱 + Pydantic 스키마 검증 |

#### 7.10.4 GPT 결과 반영 로직

- GPT 동의 → confidence 보정 (상향 +10, 최대 100)
- GPT 불일치 → 보수적 접근 (confidence 하향 -15, 50 미만 시 HOLD)
- GPT 미사용/실패 → 규칙 기반 결과 그대로 사용

### 7.11 상세 데이터 플로우

```
┌─────────────────────────────────────────────────────────────────┐
│                     Celery Worker                                │
│  Data Collector → Preprocessor → Regime Detector → Strategy     │
│       │                              │              Selector     │
│       │ READ                        │ WRITE            │        │
│  ┌────▼──────────────────────────────▼──────────────────▼───┐   │
│  │  Shared Context (per coin per cycle)                      │   │
│  │  { candles, indicators, news_sentiment, regime,           │   │
│  │    strategy, signal }                                     │   │
│  └───────────────────────────┬───────────────────────────────┘   │
│                              ▼                                   │
│                       Execution Engine                           │
└──────────────────────────────┼───────────────────────────────────┘
                 ┌─────────────┼─────────────┐
                 ▼             ▼              ▼
           PostgreSQL      MongoDB      Redis Pub/Sub
           (trade_orders)  (trade_logs   (ai:signal:
                           ai_decisions)  {user_id})
                                              │
                                         WS Hub → Client
```

| 데이터 | 저장소 | 보관 기간 |
|--------|-------|----------|
| AI 매매 주문 | PostgreSQL `trade_orders` | 영구 (5년 법적 보관) |
| AI 판단 이력 | MongoDB `ai_decisions` | 6개월~1년 |
| AI 매매 로그 | MongoDB `trade_logs` | 1년 |
| 일일 손익 | MongoDB `daily_pnl_reports` | 영구 |
| GPT 응답 원문 | MongoDB `ai_decisions.gpt_raw_response` | 6개월 |
| 실시간 AI 신호 | Redis Pub/Sub | 실시간 (비영속) |

---

## 8. 클라이언트 화면

| 화면 | 설명 | 인증 |
|------|------|------|
| 스플래시 | 앱 로딩, 토큰 갱신, 세션 복구 | X |
| 로그인/회원가입 | 이메일 인증, 소셜 로그인(Google/Apple), 비밀번호 찾기/재설정 | X |
| 메인 (코인 목록) | 거래소 탭 + 관심 코인 실시간 시세 + 코인 검색 + 스와이프 관심코인 추가 | O |
| 트레이딩 (코인 상세) | TradingView 차트 + 호가창 + 주문 (탭 방식) | O |
| 거래소 설정 | API 키 등록/관리/연결 테스트 | O |
| AI 자동매매 대시보드 | 마스터 스위치, 장세(confidence %), 전략, 카운트다운, 손익 | O |
| 자산 (포트폴리오) | 거래소별 총 자산, 코인별 보유량·평균매입가·수익률, 자산 비중 도넛차트 | O |
| 매매 내역 | 주문/체결 내역, 기간 필터, 요약 통계 | O |
| 프로필 수정 | 닉네임 변경, 아바타 업로드, 계정 삭제 (`PUT /api/v1/auth/me` + `/avatar` 활용) | O |
| 알림 (M9) | 알림 목록, 읽음/삭제, 미읽 뱃지 | O |
| 설정 | 언어, 테마, 가격 색상(한국식/글로벌), 알림 설정 | O |
| 이용약관/개인정보 | WebView 또는 마크다운 뷰어 | X |

> 상세 UI/UX는 디자인 컨셉 문서(docs/design-concept.md)를 참조한다.
> 디자인 참고: coinone.co.kr, upbit.com

**네비게이션 규칙**:
- Bottom Navigation Bar: 5탭 고정 (홈 / 트레이딩 / AI 매매 / 자산 / 더보기)
- 트레이딩 화면 내부 탭: 차트 / 호가창 / 주문 (3탭)

---

## 9. 보안

### 9.1 인증 및 접근 제어

- **인증**: JWT (access 30분, refresh 14일 Redis 저장)
- **2FA (TOTP)**: Google Authenticator 호환, 로그인·주문·API키 변경 시 2차 인증 (선택적 활성화, 강력 권장)
- **이메일 인증**: 회원가입 시 인증 코드(6자리) 이메일 발송, 10분 만료. 미인증 계정은 거래 기능 제한
- **세션 관리**: 활성 세션(디바이스) 목록 조회, 개별/전체 세션 강제 종료 지원
- **새 디바이스 알림**: 미등록 디바이스에서 로그인 시 기존 디바이스에 푸시 알림 + 이메일 발송

### 9.2 암호화 및 통신

- **암호화**: 거래소 API Key AES-256-GCM, 비밀번호 bcrypt(12)
- **통신**: HTTPS/WSS 필수 (TLS 1.2+)
- **API Key 보호**: 서버 암호화 저장, 조회 시 마스킹, 암호화 키 환경변수 관리
- **거래소 API 키 권한 검증**: 등록 시 출금 권한 감지 및 경고 (섹션 6.3 참조)

### 9.3 API 보안

- Rate Limiting, CORS 화이트리스트, Pydantic 검증
- 거래소별 서버 측 Rate Limiter (섹션 6.5 참조)

### 9.4 감사 로그 (Audit Log)

민감한 사용자 행동을 MongoDB `audit_logs` 컬렉션에 기록한다.
- **기록 대상**: 로그인/로그아웃, 비밀번호 변경, 2FA 활성화/비활성화, 거래소 API 키 등록/수정/삭제, 계정 삭제
- **기록 항목**: user_id, action, ip_address, user_agent, timestamp, details
- **보관 기간**: 1년 (TTL 인덱스)
- **접근 제한**: 사용자 본인 조회 불가, 서버 관리자 전용

### 9.5 개인정보 보호

- **동의 관리**: 회원가입 시 이용약관·개인정보처리방침 동의 이력 저장 (`user_consents` 테이블), 약관 버전 관리
- **계정 삭제 정책**: `DELETE /api/v1/auth/me` 요청 시 30일 유예 기간 후 개인정보 영구 삭제, 거래 기록은 전자금융거래법에 따라 5년 보관 (익명화 처리)
- **데이터 최소 수집**: 서비스 운영에 필요한 최소한의 개인정보만 수집

---

## 10. 비기능 요구사항

### 10.1 성능

- API 응답: 평균 200ms 이하 (p95 < 500ms)
- WebSocket 지연: 거래소 수신 후 100ms 이내
- 동시 접속: 1,000 WebSocket 연결
- 가동률: 99.5% (월간)

### 10.2 모니터링 및 에러 트래킹

- **APM**: Sentry (에러 트래킹, 서버+클라이언트) + Prometheus+Grafana (메트릭 대시보드)
- **헬스체크**: `GET /health` (DB 연결, Redis, Celery 워커 상태 포함)
- **거래소 모니터링**: 거래소 API 성공/실패율, 응답시간, Circuit Breaker 상태
- **알림**: Slack/PagerDuty 연동 — 에러율 급증, 거래소 장애, 서버 다운 시 즉시 알림
- **클라이언트 크래시**: Firebase Crashlytics (iOS/Android), Sentry (Web)

### 10.3 로깅

- **서버**: structlog JSON 로깅, 요청별 correlation_id 추적
- **로그 중앙화**: Loki + Grafana 또는 CloudWatch Logs (분산 환경 로그 수집/검색)
- **보관 기간**: 애플리케이션 로그 90일, 감사 로그 1년

### 10.4 백업 및 복구

- **PostgreSQL**: pg_dump 일일 백업 + WAL 아카이빙 (Point-in-Time Recovery). RPO: 1시간, RTO: 4시간
- **MongoDB**: mongodump 일일 백업 + oplog 기반 증분 백업. RPO: 1시간, RTO: 4시간
- **Redis**: AOF 영속화 (refresh token, rate limit 상태 보존). 재시작 시 복구 가능
- **백업 저장소**: S3 호환 스토리지, 암호화 저장, 30일 보관

### 10.5 CI/CD

- **CI**: GitHub Actions 기반 — 린트(ruff/dartanalyze), 테스트(pytest/flutter test), 코드 커버리지(80%+ 기준)
- **CD**: Docker 이미지 빌드 → 스테이징 자동 배포 → 수동 승인 후 프로덕션 배포
- **배포 전략**: Rolling Update (무중단), 롤백 1-click 지원
- **환경**: 개발(local) → 스테이징(staging) → 프로덕션(production) 3단계

### 10.6 앱 버전 관리

- `GET /api/v1/app-version` API로 최소 지원 버전 확인
- 강제 업데이트 필요 시 앱 진입 차단 + 스토어 이동 안내
- API 하위호환: v1 Deprecation 시 최소 3개월 유예, 응답 헤더에 `Sunset` 날짜 포함

---

## 11. 프로젝트 구조

### 11.1 서버

```
server/
├── app/
│   ├── main.py
│   ├── core/                      # 설정, DB, 의존성
│   │   ├── config.py
│   │   ├── database.py            # PostgreSQL (SQLAlchemy async)
│   │   ├── mongodb.py             # MongoDB (Beanie async)
│   │   ├── deps.py
│   │   └── security.py
│   ├── api/v1/                    # API 라우터
│   │   ├── auth.py                # 이메일 인증 (register, login, me, avatar)
│   │   ├── social_auth.py         # 소셜 인증 (Google, Apple OAuth)
│   │   ├── clients.py
│   │   ├── exchanges.py
│   │   ├── coins.py
│   │   ├── watchlist.py
│   │   ├── orders.py
│   │   ├── portfolio.py            # 자산/포트폴리오
│   │   ├── ai_trading.py
│   │   ├── price_alerts.py         # 가격 알림 (M9)
│   │   └── notifications.py       # 알림 (M9)
│   ├── ws/                        # WebSocket 허브
│   │   ├── hub.py
│   │   └── handlers.py
│   ├── models/                    # SQLAlchemy 모델 (PostgreSQL)
│   ├── documents/                 # Beanie 도큐먼트 (MongoDB)
│   ├── schemas/                   # Pydantic 스키마
│   │   ├── ai_trading.py          # AI 매매 요청/응답 스키마
│   │   ├── backtest.py            # 백테스팅 스키마 (M9)
│   │   └── common.py              # MetaSchema, PaginationMeta 공용
│   ├── repositories/              # DB 접근 계층
│   │   ├── base_pg.py             # PostgreSQL 베이스 (AsyncSession)
│   │   └── base_mongo.py          # MongoDB 베이스 (Beanie Document)
│   ├── services/                  # 비즈니스 로직
│   │   ├── ai_trading_service.py  # AI 매매 서비스 (trading/ 패키지 연결 유일 인터페이스)
│   │   └── backtest_service.py    # 백테스팅 서비스 (M9)
│   ├── providers/                 # 거래소 프로바이더
│   │   ├── base.py
│   │   ├── factory.py
│   │   ├── upbit.py
│   │   ├── coinone.py
│   │   ├── coinbase.py
│   │   └── binance.py
│   ├── trading/                   # AI 매매 엔진 (독립 패키지, FastAPI/DB import 금지)
│   │   ├── __init__.py            # public API: RegimeDetector, StrategySelector, ExecutionEngine
│   │   ├── types.py               # 공유 타입 (Candle, RegimeResult, TradingSignal, ExecutionResult)
│   │   ├── exceptions.py          # TradingError, InsufficientBalanceError 등
│   │   ├── indicators/            # 기술적 지표 계산 (순수 함수)
│   │   │   ├── __init__.py        # calculate_all_indicators()
│   │   │   ├── base.py            # IndicatorBase ABC
│   │   │   ├── trend.py           # MA, EMA, VWAP, MACD
│   │   │   ├── oscillator.py      # RSI, Stochastic, Williams %R, CCI
│   │   │   └── volatility.py      # Bollinger Bands, ATR, ADX
│   │   ├── regime/                # 장세 분류
│   │   │   ├── base.py            # RegimeDetector ABC
│   │   │   └── detector.py        # MarketRegimeDetector (규칙+GPT 앙상블)
│   │   ├── strategy/              # 매매 전략
│   │   │   ├── base.py            # TradingStrategy ABC
│   │   │   ├── trend_ma.py        # TrendMA 눌림목
│   │   │   ├── vwap_bounce.py     # VWAP 눌림목
│   │   │   ├── vwap_band_reversal.py  # VWAP 밴드 반전
│   │   │   ├── rsi_bb_reversal.py # RSI+볼밴+반전캔들
│   │   │   ├── rsi_divergence.py  # RSI 다이버전스 + MACD
│   │   │   └── selector.py        # StrategySelector (장세→전략 매핑)
│   │   ├── execution/             # 매매 실행
│   │   │   ├── base.py            # ExecutionEngine ABC
│   │   │   ├── engine.py          # DefaultExecutionEngine
│   │   │   └── risk_manager.py    # RiskManager (손절/익절/포지션사이징/드로다운)
│   │   └── gpt/                   # GPT 연동 분리
│   │       ├── client.py          # GPT API 클라이언트 래퍼
│   │       └── prompts.py         # 프롬프트 템플릿 상수
│   └── utils/
├── tasks/                         # Celery 태스크
│   ├── celery_app.py              # Celery 앱 설정 + Beat 스케줄 + 큐 라우팅
│   ├── ai_trading.py              # AI 매매 태스크 (run_all_active, run_single, backtest)
│   ├── news_scraper.py
│   ├── reports.py                 # 일별 PnL 리포트 생성
│   └── cleanup.py                 # 만료 토큰 정리 등
├── alembic/
├── tests/
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

### 11.2 클라이언트

```
client/
├── lib/
│   ├── main.dart
│   ├── app/
│   │   ├── router.dart
│   │   └── theme.dart
│   ├── features/                  # Feature-first 구조
│   │   ├── auth/
│   │   ├── home/
│   │   ├── trading/
│   │   ├── exchange/
│   │   ├── ai_trading/
│   │   ├── portfolio/              # 자산/포트폴리오
│   │   ├── history/
│   │   ├── notifications/         # 알림 (M9)
│   │   └── settings/
│   ├── core/
│   │   ├── api/                   # Dio 클라이언트
│   │   ├── websocket/             # WS 클라이언트
│   │   └── utils/
│   └── l10n/                      # 다국어 ARB 파일
├── assets/
├── test/
└── pubspec.yaml
```

---

## 12. 개발 마일스톤

### Phase 1 - 핵심 기능 (국내 거래소)

| 단계 | 항목 | 범위 |
|------|------|------|
| M1 | 인프라 & 프로젝트 셋업 | 모노레포 구조, Docker Compose(PostgreSQL+MongoDB+Redis), FastAPI/Flutter 골격, CI/CD(GitHub Actions, 린트/테스트/커버리지), Sentry+Prometheus 모니터링, DB 백업 설정, Loki 로그 중앙화, 스테이징 환경 |
| M2 | 인증 시스템 | 회원가입(이메일 인증 코드), 로그인, JWT, 비밀번호 찾기/재설정, 소셜 로그인(Google/Apple), 프로필 아바타, 클라이언트 관리, 개인정보 동의 이력 관리 (서버+클라이언트) |
| M3 | 거래소 추상화 & Upbit | ExchangeProvider ABC(get_trading_fee/verify_api_key 포함), Factory, Upbit REST/WS 구현, Circuit Breaker, 거래소별 Rate Limiter, API 키 권한 검증(출금 권한 경고) |
| M4 | 코인 목록 & 관심 코인 | 코인 마스터, 검색, 관심 코인 CRUD(스와이프), WS 시세 허브+연결 상태 UI (서버+클라이언트) |
| M5 | CoinOne 연동 | CoinOne Provider 구현 (M3 인터페이스 준수, Circuit Breaker/Rate Limiter 포함) |
| M6 | 트레이딩 & 자산 | TradingView 차트, 호가창, 주문 실행(시장가/지정가, 수수료 표시, 미체결 일괄 취소), 자산 포트폴리오 화면, 거래소 설정 (서버+클라이언트) |
| M7 | AI 자동매매 | 마스터 스위치, 기술적 지표, 장세 분석(confidence %), 전략 선택, Celery 5분 주기+카운트다운, GPT 연동, 대시보드 |
| M8 | 통계 & 리포트 & 기타 | 일별/누적 손익, 매매 로그, 통계 UI, 프로필 수정, 가격 색상 설정, 이용약관/개인정보 화면, 감사 로그 |
| M9 | 고도화 & 보안 강화 | 2FA(TOTP), 세션 관리(활성 목록/강제 종료/전체 로그아웃), 새 디바이스 로그인 알림, 가격 알림 설정, 백테스팅, 푸시 알림(가격/AI매매/체결 세분화), 알림 목록 화면, 생체 인증, 손익 미니 차트, 성능 최적화 |

### Phase 2 - 확장 (해외 거래소)

| 단계 | 항목 | 범위 |
|------|------|------|
| M10 | Coinbase 연동 | Coinbase Provider 구현 |
| M11 | Binance 연동 | Binance Provider 구현 |
| M12 | 다국어 완성 | ja, zh, es 번역 및 검수 |
| M13 | 확장 기능 | 시장 전체 현황(시가총액, BTC 도미넌스), 코인 상세 정보(CoinGecko 연동), 입출금 주소/이력 조회, 거래소 간 가격 비교, 차트 설정 저장, 앱 강제 업데이트, 수평 확장(K8s) |

### 병렬 작업 가이드

```
M1 완료 후 병렬 가능:
  - M2-a 서버 기본 인증(이메일) / M2-b 클라이언트 인증(mock) / M3 Upbit Provider
  - M2-a 완료 후: M2-c 소셜 로그인(Google/Apple) / M2-d 아바타 업로드 + File Storage

M2+M3 완료 후 병렬 가능:
  - M4 코인&관심코인 / M5 CoinOne / 거래소 설정 UI

M4+M6 완료 후:
  - M7 AI 엔진(서버) / M7 AI 대시보드(클라이언트, mock)

M7+M8 완료 후:
  - M9-a 2FA+세션 관리+디바이스 알림 / M9-b 가격 알림+푸시 알림(서버+FCM) / M9-c 알림 화면(클라이언트) / M9-d 백테스팅 / M9-e 생체 인증
```
