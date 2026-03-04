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
| 인증 | JWT (access 30분 + refresh 14일) |
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
  ├──< user_exchange_accounts ──< watchlist_coins
  │                                     │
  │                                     ▼
  │                            ai_trading_configs
  │
  └──< trade_orders
```

| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| users | 회원 | email, password_hash, nickname, language, theme |
| clients | 클라이언트/디바이스 | user_id, device_type, fcm_token |
| user_exchange_accounts | 거래소 계정 | user_id, exchange_type, api_key_encrypted, api_secret_encrypted |
| coins | 코인 마스터 | symbol, name_ko, name_en, exchange_type, market_code |
| watchlist_coins | 관심 코인 | user_id, coin_id, exchange_account_id, sort_order |
| ai_trading_configs | AI 매매 설정 | watchlist_coin_id, is_enabled, max_investment_amount, stop_loss/take_profit |
| trade_orders | 매매 주문 | order_type, order_method, price, quantity, status, is_ai_order |

### 4.3 MongoDB (비정형/시계열 데이터)

| 컬렉션 | 설명 | 특징 |
|--------|------|------|
| trade_logs | AI 매매 로그 | reasoning(비정형), strategy_params(가변 구조) |
| daily_pnl_reports | 일별 손익 리포트 | 집계 데이터, 빠른 조회 |
| candle_data | 캔들/시세 히스토리 | Time Series 컬렉션, TTL 인덱스 |
| news_data | 뉴스 스크랩 | 비정형 텍스트, 임베딩 벡터 |
| ai_decisions | AI 판단 이력 | 장세 분석 결과, GPT 응답 원문 |

### 4.4 크로스DB 설계 주의사항

- **trade_logs(Mongo) → trade_orders(PG) 참조**: DB 레벨 조인 불가. trade_logs에 order 스냅샷(price, quantity, order_type) 비정규화 저장
- **daily_pnl_reports 집계**: PG(trade_orders) + Mongo(trade_logs) 동시 조회 필요. `report_date + user_id` 기준 upsert로 멱등성 보장
- **Beanie Document → API 응답**: `_id`, `revision_id` 등 내부 필드 노출 방지. `ResponseSchema.model_validate(document)` 변환 패턴 사용

> 상세 스키마(컬럼 타입, 인덱스, 제약조건, 도큐먼트 구조)는 DB 설계 태스크에서 정의한다.

### 4.4 Redis 활용

| 용도 | 키 패턴 |
|------|---------|
| Refresh Token | `auth:refresh:{user_id}:{client_id}` |
| Rate Limiting | `rate:{ip}`, `rate:{user_id}` |
| 실시간 시세 Pub/Sub | `ticker:{exchange}:{market}` |
| Celery 브로커/결과 | Celery 기본 설정 |

---

## 5. API 설계

### 5.1 REST API

| 그룹 | 주요 엔드포인트 |
|------|----------------|
| 인증 | `POST /api/v1/auth/register, login, refresh, logout` / `GET,PUT /api/v1/auth/me` |
| 클라이언트 | `POST,GET /api/v1/clients` / `DELETE /api/v1/clients/{id}` |
| 거래소 계정 | `POST,GET /api/v1/exchanges` / `PUT,DELETE /api/v1/exchanges/{id}` / `POST .../verify` |
| 코인 | `GET /api/v1/coins` / `GET /api/v1/coins/{id}` |
| 관심 코인 | `GET,POST /api/v1/watchlist` / `DELETE /api/v1/watchlist/{id}` / `PUT .../reorder` |
| 주문 | `POST,GET /api/v1/orders` / `GET,DELETE /api/v1/orders/{id}` / `GET /api/v1/orders?status=open` |
| AI 매매 | `POST,GET /api/v1/ai-trading/configs` / `PUT .../configs/{id}` / `PATCH .../configs/{id}/activation` |
| AI 통계 | `GET /api/v1/ai-trading/logs` / `GET .../stats/daily` / `GET .../stats/total` |
| 헬스체크 | `GET /health` |

### 5.2 WebSocket

단일 연결 + 구독 메시지 방식으로 설계한다.

```
연결: ws://.../ws/v1?token={access_token}

구독 요청: { "action": "subscribe", "channel": "ticker", "exchange": "upbit", "market": "KRW-BTC" }
구독 해제: { "action": "unsubscribe", "channel": "ticker", "exchange": "upbit", "market": "KRW-BTC" }

채널 종류: ticker(시세), orderbook(호가), trades(체결), my-orders(내 주문)
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
    async def place_order(order) -> OrderResult
    async def cancel_order(order_id) -> bool
    async def get_balance() -> list[Balance]

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

### 6.3 거래소 인증

| 거래소 | 인증 방식 |
|--------|-----------|
| Upbit | JWT (access key + secret key 서명) |
| CoinOne | HMAC-SHA512 |
| Coinbase | API Key + HMAC-SHA256 |
| Binance | API Key + HMAC-SHA256 query string |

### 6.4 개발자 문서

- Upbit: https://docs.upbit.com/kr/reference/api-overview
- CoinOne: https://docs.coinone.co.kr/reference/range-unit
- Coinbase: https://docs.cdp.coinbase.com/api-reference/v2/introduction
- Binance: https://www.binance.com/en/binance-api

---

## 7. AI 자동매매 시스템

### 7.1 전체 흐름

```
Celery Beat (5분 주기)
    → 장세 분석 (Market Regime Detection)
    → 전략 선택 (Strategy Selection)
    → 매매 실행 (Execution Engine)
    → 로그 & 통계 (Logging)
```

### 7.2 장세 분석

- **입력**: 뉴스 데이터, 2일치 5분봉(~576캔들), 기술적 지표(MA, VWAP, RSI, MACD, Bollinger Bands, ADX)
- **출력**: Trend(추세) / Range(횡보) / Transition(전환) 분류

### 7.3 장세별 전략

| 장세 | 전략 | 핵심 |
|------|------|------|
| Trend | TrendMA 눌림목, VWAP 눌림목 | MA/VWAP 지지 반등 매매 |
| Range | VWAP 밴드 반전, RSI+볼밴+반전캔들 | 밴드 경계 반전 매매 |
| Transition | RSI 다이버전스 + MACD | 추세 전환 포착 |

### 7.4 리스크 관리

- 1회 최대 투자: 총 자산 대비 10% (설정 가능)
- 손절: -2% / 익절: +3% (설정 가능)
- 일일 최대 손실: -5% (설정 가능)
- GPT 연동: 장세 판단 및 전략 선택 보조

### 7.5 통계

- 매매 로그: 진입/청산 가격, 전략, AI 판단 근거
- 일별 통계: 거래 횟수, 승률, 총 손익
- 누적 통계: 총 수익률, 샤프 비율, MDD

---

## 8. 클라이언트 화면

| 화면 | 설명 | 인증 |
|------|------|------|
| 스플래시 | 앱 로딩 | X |
| 로그인/회원가입 | 이메일 인증 | X |
| 메인 (코인 목록) | 거래소 탭 + 관심 코인 실시간 시세 | O |
| 트레이딩 (코인 상세) | TradingView 차트 + 호가창 + 주문 | O |
| 거래소 설정 | API 키 등록/관리 | O |
| AI 자동매매 대시보드 | AI on/off, 장세, 전략, 손익 차트 | O |
| 매매 내역 | 주문/체결 내역 | O |
| 설정 | 언어, 테마, 알림 | O |

> 상세 UI 와이어프레임은 디자인 태스크에서 정의한다.
> 디자인 참고: coinone.co.kr, upbit.com

---

## 9. 보안

- **인증**: JWT (access 30분, refresh 14일 Redis 저장)
- **암호화**: 거래소 API Key AES-256-GCM, 비밀번호 bcrypt(12)
- **통신**: HTTPS/WSS 필수 (TLS 1.2+)
- **API 보안**: Rate Limiting, CORS 화이트리스트, Pydantic 검증
- **API Key 보호**: 서버 암호화 저장, 조회 시 마스킹, 암호화 키 환경변수 관리

---

## 10. 비기능 요구사항

- API 응답: 평균 200ms 이하 (p95 < 500ms)
- WebSocket 지연: 거래소 수신 후 100ms 이내
- 동시 접속: 1,000 WebSocket 연결
- 가동률: 99.5% (월간)
- 로깅: structlog JSON 로깅
- 모니터링: `GET /health`, 거래소 API 성공/실패율

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
│   │   ├── auth.py
│   │   ├── clients.py
│   │   ├── exchanges.py
│   │   ├── coins.py
│   │   ├── watchlist.py
│   │   ├── orders.py
│   │   └── ai_trading.py
│   ├── ws/                        # WebSocket 허브
│   │   ├── hub.py
│   │   └── handlers.py
│   ├── models/                    # SQLAlchemy 모델 (PostgreSQL)
│   ├── documents/                 # Beanie 도큐먼트 (MongoDB)
│   ├── schemas/                   # Pydantic 스키마
│   ├── repositories/              # DB 접근 계층
│   │   ├── base_pg.py             # PostgreSQL 베이스 (AsyncSession)
│   │   └── base_mongo.py          # MongoDB 베이스 (Beanie Document)
│   ├── services/                  # 비즈니스 로직
│   ├── providers/                 # 거래소 프로바이더
│   │   ├── base.py
│   │   ├── factory.py
│   │   ├── upbit.py
│   │   ├── coinone.py
│   │   ├── coinbase.py
│   │   └── binance.py
│   ├── trading/                   # AI 매매 엔진 (독립 패키지)
│   │   ├── regime_detector.py
│   │   ├── strategy_selector.py
│   │   ├── execution_engine.py
│   │   └── indicators.py
│   └── utils/
├── tasks/                         # Celery 태스크
│   ├── ai_trading.py
│   └── news_scraper.py
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
│   │   ├── history/
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
| M1 | 인프라 & 프로젝트 셋업 | 모노레포 구조, Docker Compose(PostgreSQL+MongoDB+Redis), FastAPI/Flutter 골격, CI/CD |
| M2 | 인증 시스템 | 회원가입, 로그인, JWT, 클라이언트 관리 (서버+클라이언트) |
| M3 | 거래소 추상화 & Upbit | ExchangeProvider ABC, Factory, Upbit REST/WS 구현 |
| M4 | 코인 목록 & 관심 코인 | 코인 마스터, 관심 코인 CRUD, WS 시세 허브 (서버+클라이언트) |
| M5 | CoinOne 연동 | CoinOne Provider 구현 (M3 인터페이스 준수) |
| M6 | 트레이딩 화면 | TradingView 차트, 호가창, 주문 실행, 거래소 설정 (서버+클라이언트) |
| M7 | AI 자동매매 | 기술적 지표, 장세 분석, 전략 선택, Celery 5분 주기, GPT 연동, 대시보드 |
| M8 | 통계 & 리포트 | 일별/누적 손익, 매매 로그, 통계 UI |

### Phase 2 - 확장 (해외 거래소)

| 단계 | 항목 | 범위 |
|------|------|------|
| M9 | Coinbase 연동 | Coinbase Provider 구현 |
| M10 | Binance 연동 | Binance Provider 구현 |
| M11 | 다국어 완성 | ja, zh, es 번역 및 검수 |
| M12 | 고도화 | 백테스팅, 푸시 알림, 성능 최적화 |

### 병렬 작업 가이드

```
M1 완료 후 병렬 가능:
  - M2 서버 인증 / M2 클라이언트 인증(mock) / M3 Upbit Provider

M2+M3 완료 후 병렬 가능:
  - M4 코인&관심코인 / M5 CoinOne / 거래소 설정 UI

M4+M6 완료 후:
  - M7 AI 엔진 (서버) / M7 AI 대시보드 (클라이언트, mock 기반)
```
