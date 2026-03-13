# v1-8 거래소 추상화 계층 (Exchange Abstraction Layer) - 설계서

> **작성**: project-architect (시스템 아키텍처/흐름/구현계획), code-architect (타입/ABC/예외/팩토리)
> **대상 태스크**: v1-8 — 거래소 공통 인터페이스(ABC), Provider Factory, Circuit Breaker, Rate Limiting
> **현재 상태**: 구현 완료 — 66/66 테스트 통과, 코드 리뷰 승인 (CRITICAL 0, WARNING 0)

---

## 1. 개요

모든 거래소(Upbit, CoinOne, Coinbase, Binance)를 공통 인터페이스(ABC)로 추상화하고, Provider Factory로 런타임에 거래소를 선택하며, Circuit Breaker 패턴과 거래소별 Rate Limiting으로 안정성을 확보한다.

**의존성**: v1-5 (JWT 인증), v1-3 (Redis 캐시/Pub/Sub) 완료.

**기존 코드 활용**:
- `server/app/core/rate_limiter.py` — TokenBucketRateLimiter, ExchangeRateLimiter 이미 구현 (재사용)
- `server/app/core/redis_keys.py` — `RedisKey.rate_exchange()`, `RedisTTL`, `PubSubChannel` 정의됨
- `server/app/core/pubsub.py` — RedisPublisher (시세 발행)
- `server/app/ws/subscribers.py` — PubSubSubscriber (Redis → WS 브리지)
- `server/app/services/market_cache_service.py` — 시세/캔들/호가/지표 Redis 캐시
- `server/app/core/config.py` — `EXCHANGE_API_KEY_SECRET` (API 키 암호화용)
- `server/app/providers/__init__.py` — 빈 패키지 (스캐폴딩)

### 1.1 핵심 원칙

- **ABC 추상화**: 거래소별 구현을 숨기고 공통 인터페이스만 노출
- **기존 인프라 재사용**: Rate Limiter, Redis 캐시, Pub/Sub 기존 구현 그대로 활용
- **Circuit Breaker**: 거래소 장애 시 빠른 실패로 서비스 안정성 확보
- **점진적 구현**: v1-8은 추상화 계층 + Mock만 구현, 실제 거래소는 M3(Upbit), M5(CoinOne) 등에서 구현
- **trading 패키지 독립성**: `trading/` 패키지는 FastAPI/DB import 금지 — providers를 통해서만 거래소 접근

---

## 2. 시스템 아키텍처

### 2.1 컴포넌트 관계도

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FastAPI Server                               │
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │ api/v1/     │  │ services/   │  │ trading/    │                 │
│  │ exchanges.py│  │ exchange_   │  │ execution/  │                 │
│  │ orders.py   │  │ service.py  │  │ engine.py   │                 │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                 │
│         │                │                │                          │
│         └────────────────┼────────────────┘                          │
│                          │                                           │
│                 ┌────────▼────────┐                                  │
│                 │ ExchangeProvider │ ← ABC (공통 인터페이스)          │
│                 │ Factory          │                                  │
│                 └────────┬────────┘                                  │
│                          │ create(exchange_type)                     │
│         ┌────────────────┼────────────────┐                          │
│         │                │                │                          │
│  ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐                  │
│  │ CircuitBreaker│ │ RateLimiter │ │ HTTP/WS     │                  │
│  │ (per exchange)│ │ (기존 재사용) │ │ BaseClient  │                  │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘                  │
│         └────────────────┼────────────────┘                          │
│                          │                                           │
│  ┌───────────────────────┼───────────────────────────────────┐      │
│  │         Exchange Provider Implementations                  │      │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │      │
│  │  │  Upbit   │ │ CoinOne  │ │ Coinbase │ │ Binance  │     │      │
│  │  │ Provider │ │ Provider │ │ Provider │ │ Provider │     │      │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘     │      │
│  │  ┌──────────┐                                              │      │
│  │  │  Mock    │ (테스트/개발용)                               │      │
│  │  │ Provider │                                              │      │
│  │  └──────────┘                                              │      │
│  └────────────────────────────────────────────────────────────┘      │
│                          │                                           │
│         ┌────────────────┼────────────────┐                          │
│         │                │                │                          │
│  ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐                  │
│  │ Redis Cache │ │ Redis       │ │ PostgreSQL  │                  │
│  │ (시세/호가)  │ │ Pub/Sub     │ │ (주문/계정) │                  │
│  └─────────────┘ └─────────────┘ └─────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 핵심 데이터 흐름

```
[REST 시세 조회]
  Client → API → ExchangeService → Factory.get(exchange) → Provider.get_ticker()
    → CircuitBreaker.execute() → RateLimiter.acquire() → HTTP Client → Exchange API
    → 결과 → MarketCacheService.set_ticker() → Redis Cache
    → 응답 → Client

[WebSocket 시세 스트리밍]
  Exchange WS ←→ Provider.subscribe_ticker()
    → on_message → MarketCacheService.set_ticker() → Redis Cache
                 → RedisPublisher.publish_ticker() → Redis Pub/Sub
                 → PubSubSubscriber → WSHub → Client WebSocket

[주문 실행]
  Client → API → OrderService → Factory.get(exchange) → Provider.place_order()
    → CircuitBreaker.execute() → RateLimiter.acquire() → HTTP Client → Exchange API
    → 결과 → PostgreSQL (주문 기록) + MongoDB (매매 로그)
    → RedisPublisher.publish_my_orders() → Client WebSocket

[AI 자동매매]
  Celery Beat(5분) → AITradingService → Factory.get(exchange)
    → Provider.get_candles() → 기술적 지표 계산
    → 장세 분석 → 전략 선택 → Provider.place_order()
    → 결과 기록 (PG + Mongo)
```

### 2.3 Provider 계층 구조 (클래스 다이어그램)

```
                    ┌─────────────────────┐
                    │  ExchangeRestProvider│ (ABC)
                    │─────────────────────│
                    │+ get_ticker()       │
                    │+ get_orderbook()    │
                    │+ get_candles()      │
                    │+ place_order()      │
                    │+ cancel_order()     │
                    │+ get_balance()      │
                    │+ get_trading_fee()  │
                    │+ verify_api_key()   │
                    └─────────┬───────────┘
                              │
                    ┌─────────────────────┐
                    │ExchangeStreamProvider│ (ABC)
                    │─────────────────────│
                    │+ connect()          │
                    │+ disconnect()       │
                    │+ subscribe_ticker() │
                    │+ subscribe_orderbook│
                    │+ unsubscribe()      │
                    │+ on_message()       │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  ExchangeProvider    │ (ABC, 통합)
                    │─────────────────────│
                    │+ exchange_type      │
                    │+ is_connected       │
                    │+ initialize()       │
                    │+ close()            │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼─────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │BaseExchange   │ │  Upbit      │ │  Mock       │
    │Provider       │ │  Provider   │ │  Provider   │
    │(공통 HTTP/WS) │ │  (M3 구현)  │ │  (v1-8 구현)│
    └───────────────┘ └─────────────┘ └─────────────┘
```

---

## 3. 파일 구조

### 3.1 신규 파일

```
server/app/
├── providers/
│   ├── __init__.py                  # public API: ExchangeProvider, Factory 등 re-export
│   ├── types.py                     # ST1: 공통 데이터 모델 (Ticker, Orderbook, Candle 등)
│   ├── enums.py                     # ST1: 거래소 타입, 주문 타입, 주문 상태 등 열거형
│   ├── exceptions.py                # ST4: ExchangeError 계층 (거래소 도메인 예외)
│   ├── base.py                      # ST2,3,4: ABC 정의 (Rest, Stream, Provider)
│   ├── circuit_breaker.py           # ST6: Circuit Breaker 패턴 구현
│   ├── factory.py                   # ST7: ExchangeProviderFactory + Registry
│   ├── base_impl.py                 # ST9: BaseExchangeProvider (공통 HTTP/WS 클라이언트)
│   └── mock_provider.py             # ST10: MockExchangeProvider (테스트/개발용)
│
├── core/
│   └── exceptions.py                # 수정: ExchangeErrors 클래스 추가
│
└── services/
    └── exchange_service.py          # ST9: ExchangeService (Provider 오케스트레이션)

server/tests/
├── unit/
│   ├── test_circuit_breaker.py      # Circuit Breaker 단위 테스트
│   ├── test_exchange_types.py       # 데이터 모델 단위 테스트
│   ├── test_exchange_factory.py     # Factory 단위 테스트
│   └── test_mock_provider.py        # Mock Provider 단위 테스트
└── integration/
    └── test_exchange_provider.py    # Provider 통합 테스트 (Mock 기반)
```

### 3.2 수정 파일

```
server/app/
├── core/
│   ├── config.py                    # 설정: Circuit Breaker 임계값, 거래소별 설정
│   ├── deps.py                      # DI: ExchangeProviderFactory, ExchangeService 팩토리 + 타입 별칭
│   ├── exceptions.py                # 에러: ExchangeErrors 클래스 추가
│   └── redis_keys.py               # Redis: Circuit Breaker 상태 키 추가
├── providers/
│   └── __init__.py                  # re-export 정의
└── main.py                         # lifespan: Provider Factory 초기화/정리
```

---

## 4. Circuit Breaker 설계

### 4.1 상태 머신

```
                    성공
              ┌──────────────┐
              │              │
              ▼              │
         ┌─────────┐        │
    ─────▶│ CLOSED  │────────┘
         │(정상)    │
         └────┬────┘
              │ 실패 임계 도달
              │ (연속 5회 OR 30초 내 50% 초과)
              ▼
         ┌─────────┐
         │  OPEN   │── 요청 즉시 거부 (fail-fast)
         │(차단)    │   ExchangeErrors.circuit_open() 반환
         └────┬────┘
              │ recovery_timeout 경과 (60초)
              ▼
         ┌─────────┐
         │HALF-OPEN│── 제한된 요청 허용 (1회)
         │(시험)    │
         └────┬────┘
              │
         ┌────┴────┐
         │         │
     성공 ▼     실패 ▼
    CLOSED      OPEN
```

### 4.2 Circuit Breaker 설정

```python
@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5          # 연속 실패 허용 횟수
    failure_rate_threshold: float = 0.5 # 실패율 임계값 (50%)
    failure_rate_window: int = 30       # 실패율 측정 윈도우 (초)
    recovery_timeout: int = 60          # OPEN → HALF-OPEN 대기 시간 (초)
    half_open_max_calls: int = 1        # HALF-OPEN 상태에서 허용 요청 수
```

### 4.3 구현 특징

- **거래소별 독립 인스턴스**: 각 거래소(Upbit, CoinOne 등)는 독립된 CircuitBreaker를 가짐
- **인메모리 상태**: 단일 서버 환경이므로 Redis 불필요 (멀티 인스턴스 시 Redis 확장 가능)
- **슬라이딩 윈도우**: 최근 `failure_rate_window`초 내 성공/실패 기록으로 실패율 계산
- **스레드 안전**: asyncio.Lock으로 상태 전환 보호
- **이벤트 콜백**: 상태 전환 시 로깅 + 선택적 콜백 (알림 등)

### 4.4 Circuit Breaker 시퀀스

```
Caller              CircuitBreaker           Provider            Exchange
  │                       │                      │                   │
  ├── execute(fn) ───────>│                      │                   │
  │                       ├── check_state()      │                   │
  │                       │   CLOSED? ──────────>│                   │
  │                       │                      ├── fn() ──────────>│
  │                       │                      │<── response ──────┤
  │                       │<── success ──────────┤                   │
  │                       ├── record_success()   │                   │
  │<── result ────────────┤                      │                   │
  │                       │                      │                   │
  │ [실패 시]              │                      │                   │
  │                       │<── exception ────────┤                   │
  │                       ├── record_failure()   │                   │
  │                       │   threshold 도달?     │                   │
  │                       │   YES → state=OPEN   │                   │
  │<── ExchangeError ─────┤                      │                   │
  │                       │                      │                   │
  │ [OPEN 상태에서]         │                      │                   │
  ├── execute(fn) ───────>│                      │                   │
  │                       ├── check_state()      │                   │
  │                       │   OPEN → fail-fast   │                   │
  │<── CircuitOpenError ──┤                      │                   │
```

---

## 5. Rate Limiter 통합

### 5.1 기존 구현 재사용

`core/rate_limiter.py`의 `ExchangeRateLimiter`를 그대로 사용한다. 이미 거래소별 이중 Token Bucket (초당 + 분당)이 구현되어 있다.

| 거래소 | 초당 | 분당 | 비고 |
|--------|------|------|------|
| Upbit | 10회 | 600회 | 주문/조회 통합 |
| CoinOne | 10회 | 300회 | |
| Coinbase | 10회 | 300회 | |
| Binance | 20회 | 1,200회 | Weight 기반 |

### 5.2 Provider 내 Rate Limiter 연동

Rate Limiter는 `BaseExchangeProvider`에서 자동 적용된다. 각 API 호출 전에 `ExchangeRateLimiter.acquire()`를 호출하고, 실패 시 `ExchangeErrors.rate_limited()` 예외를 발생시킨다.

```
Provider.get_ticker()
  → BaseExchangeProvider._execute_rest()
    → rate_limiter.acquire(exchange, user_id)
      → 허용: circuit_breaker.execute(http_call)
      → 거부: raise ExchangeErrors.rate_limited(retry_after_ms)
```

---

## 6. 의존성 흐름도 (DI 체인)

### 6.1 DI 구성

```
api/v1/exchanges.py ──> ExchangeService ──┬──> ExchangeProviderFactory
                                           │     └──> Registry[ExchangeProvider]
                                           ├──> MarketCacheService (Redis)
                                           ├──> ExchangeRateLimiter (Redis)
                                           └──> RedisPublisher (Pub/Sub)

api/v1/orders.py ─────> OrderService ─────┬──> ExchangeProviderFactory
                                           ├──> OrderRepository (PostgreSQL)
                                           └──> AuditService (MongoDB)

trading/execution/ ───> AITradingService ─┬──> ExchangeProviderFactory
                                           ├──> MarketCacheService
                                           └──> MongoDB (AI 로그)
```

### 6.2 deps.py 추가

```python
# core/deps.py — 신규 DI 팩토리

from app.providers.factory import ExchangeProviderFactory

def get_exchange_factory() -> ExchangeProviderFactory:
    """앱 시작 시 초기화된 싱글턴 Factory 반환."""
    return ExchangeProviderFactory.instance()

def get_exchange_service(
    factory: ExchangeProviderFactory = Depends(get_exchange_factory),
    cache: MarketCacheService = Depends(get_market_cache_service),
    rate_limiter: ExchangeRateLimiter = Depends(get_exchange_rate_limiter),
) -> ExchangeService:
    return ExchangeService(factory, cache, rate_limiter)

# ── Type aliases ──
ExchangeFactoryDep = Annotated[ExchangeProviderFactory, Depends(get_exchange_factory)]
ExchangeServiceDep = Annotated[ExchangeService, Depends(get_exchange_service)]
```

### 6.3 Lifespan 통합

```python
# main.py — lifespan 확장
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 기존 DB/Redis 초기화 ...

    # Exchange Provider Factory 싱글턴 초기화 + 기본 등록
    factory = ExchangeProviderFactory.init(redis=redis_client)
    factory.register_defaults()  # Mock Provider로 모든 거래소 기본 등록

    yield

    # Exchange Provider 정리
    await factory.close_all()

    # ... 기존 DB/Redis 종료 ...
```

---

## 7. API 키 권한 검증 설계

### 7.1 검증 흐름

```
User                    API                     Provider              Exchange
  │                       │                        │                      │
  ├── POST /exchanges     │                        │                      │
  │   /verify-key ───────>│                        │                      │
  │   { exchange, key,    │                        │                      │
  │     secret }          │                        │                      │
  │                       ├── factory.create() ───>│                      │
  │                       │                        ├── verify_api_key() ─>│
  │                       │                        │   (거래소 API 호출)    │
  │                       │                        │<── permissions ──────┤
  │                       │<── ApiKeyPermission ───┤                      │
  │                       │                        │                      │
  │                       ├── 권한 확인             │                      │
  │                       │   can_trade? can_view?  │                      │
  │                       │                        │                      │
  │                       ├── 키 암호화 → DB 저장   │                      │
  │<── { permissions,    <┤                        │                      │
  │      warnings }       │                        │                      │
```

### 7.2 권한 레벨

```python
class ApiKeyPermission(str, Enum):
    VIEW_BALANCE = "view_balance"    # 잔고 조회
    VIEW_ORDERS = "view_orders"      # 주문 조회
    TRADE = "trade"                  # 주문 실행
    WITHDRAW = "withdraw"            # 출금 (경고 대상)
```

**경고 시스템**: `WITHDRAW` 권한이 포함된 키는 경고 메시지를 반환. 불필요한 권한은 보안 위험.

---

## 8. 테스트 전략

### 8.1 단위 테스트

| 테스트 대상 | 파일 | 주요 케이스 |
|------------|------|------------|
| Circuit Breaker | `test_circuit_breaker.py` | 상태 전환(CLOSED→OPEN→HALF-OPEN→CLOSED), 연속 실패 임계값, 실패율 임계값, recovery timeout, 동시성 |
| 데이터 모델 | `test_exchange_types.py` | Ticker/Orderbook/Candle 직렬화, 필드 검증, 거래소별 변환 |
| Factory | `test_exchange_factory.py` | 등록/조회, 미등록 거래소 에러, 싱글턴 |
| Mock Provider | `test_mock_provider.py` | 모든 ABC 메서드 구현 확인, 시뮬레이션 데이터 정합성 |

### 8.2 통합 테스트

| 테스트 대상 | 파일 | 주요 케이스 |
|------------|------|------------|
| Provider 흐름 | `test_exchange_provider.py` | Mock Provider로 전체 흐름 검증: 시세 조회 → 캐시, 주문 실행 → 기록, Rate Limit 동작, Circuit Breaker 트리거 |

### 8.3 테스트 원칙

- **Mock Provider 활용**: 실제 거래소 API 호출 없이 전체 흐름 검증
- **Circuit Breaker 테스트**: 시간 제어를 위해 `freezegun` 또는 수동 시간 주입
- **Rate Limiter 테스트**: 기존 `ExchangeRateLimiter` 테스트 활용 (v1-3에서 구현 완료)
- **ABC 준수 검증**: `isinstance(provider, ExchangeProvider)` + 모든 추상 메서드 구현 확인

---

## 9. 서브태스크 의존성 그래프

```
ST1: 공통 데이터 모델 + 열거형 ──────────────────────────────────────┐
     (types.py, enums.py)                                            │
                                                                      │
ST2: ExchangeRestProvider ABC ────────┐                              │
     (base.py)                         │                              │
                                       │                              │
ST3: ExchangeStreamProvider ABC ──────┤                              │
     (base.py)                         │                              │
                                       │                              │
                              ┌────────┴────────┐                     │
                              │ ST4: ExchangeProvider 통합 + 예외 계층 │
                              │ (base.py, exceptions.py)              │
                              └────────┬────────┘                     │
                                       │                              │
                    ┌──────────────────┼──────────────────┐           │
                    │                  │                   │           │
           ┌────────▼────────┐ ┌──────▼──────┐  ┌────────▼────────┐  │
           │ ST5: Rate Limiter│ │ST6: Circuit │  │ST8: API 키 권한 │  │
           │ 통합 (기존 재사용) │ │Breaker 구현 │  │검증 시스템       │  │
           └────────┬────────┘ └──────┬──────┘  └────────┬────────┘  │
                    │                  │                   │           │
                    └──────────────────┼───────────────────┘           │
                                       │                              │
                              ┌────────▼────────┐                     │
                              │ ST7: Factory +   │                     │
                              │ Provider Registry │                    │
                              └────────┬────────┘                     │
                                       │                              │
                              ┌────────▼────────┐                     │
                              │ ST9: BaseExchange│                    │
                              │ Provider 구현     │                    │
                              │ (공통 HTTP/WS)    │                    │
                              └────────┬────────┘                     │
                                       │                              │
                              ┌────────▼────────┐                     │
                              │ ST10: Mock       │                    │
                              │ Provider + 테스트 │                    │
                              └─────────────────┘                     │
```

### 병렬 작업 가능 그룹

| Phase | 태스크 | 선행 조건 | 산출물 |
|-------|--------|-----------|--------|
| Phase 1 | ST1 | 없음 | `types.py`, `enums.py` |
| Phase 2 | ST2, ST3 (병렬) | ST1 | `base.py` (ABC 정의) |
| Phase 3 | ST4 | ST2, ST3 | `base.py` (ExchangeProvider), `exceptions.py` |
| Phase 4 | ST5, ST6, ST8 (병렬) | ST4 | Rate Limiter 통합, `circuit_breaker.py`, API 키 검증 |
| Phase 5 | ST7 | ST4, ST5, ST6 | `factory.py` |
| Phase 6 | ST9 | ST5, ST6, ST8 | `base_impl.py`, `exchange_service.py` |
| Phase 7 | ST10 | ST9 | `mock_provider.py`, 단위/통합 테스트 |

---

## 10. config.py 추가 설정

```python
# core/config.py — 신규 설정 항목

# Circuit Breaker
CB_FAILURE_THRESHOLD: int = 5           # 연속 실패 허용 횟수
CB_FAILURE_RATE_THRESHOLD: float = 0.5  # 실패율 임계값
CB_FAILURE_RATE_WINDOW: int = 30        # 실패율 윈도우 (초)
CB_RECOVERY_TIMEOUT: int = 60           # OPEN → HALF-OPEN 대기 (초)

# Exchange Provider
EXCHANGE_HTTP_TIMEOUT: int = 10         # HTTP 요청 타임아웃 (초)
EXCHANGE_WS_PING_INTERVAL: int = 30     # WebSocket ping 간격 (초)
EXCHANGE_WS_RECONNECT_MAX: int = 5      # WS 재연결 최대 시도
EXCHANGE_WS_RECONNECT_DELAY: float = 1.0  # WS 재연결 초기 대기 (초)
```

---

## 11. Redis 키 추가

```python
# core/redis_keys.py — 신규 키 패턴

class RedisKey:
    # ── Circuit Breaker (향후 멀티 인스턴스 확장 시) ──
    @staticmethod
    def circuit_breaker(exchange: str) -> str:
        """Circuit Breaker 상태 (향후 Redis 기반 확장 시 사용)."""
        return f"cb:{exchange}"

class RedisTTL:
    # ── Circuit Breaker ──
    CB_STATE = 300  # 5분 (Circuit Breaker 상태 TTL)
```

---

## 12. 의존 라이브러리

| 패키지 | 용도 | 버전 | 비고 |
|--------|------|------|------|
| `httpx` | 비동기 HTTP 클라이언트 | >=0.27 | v1-6에서 이미 추가 (JWKS fetch용) |
| `websockets` | WebSocket 클라이언트 | >=12.0 | 신규 추가 |

> `httpx`는 이미 의존성에 포함. `websockets`만 신규 추가 필요.

---

## 13. 보안 고려사항

### 13.1 API 키 보안

- **암호화 저장**: 거래소 API 키/시크릿은 AES-256-GCM으로 암호화 후 PostgreSQL에 저장
- **키**: `EXCHANGE_API_KEY_SECRET` 환경변수 (기존 `core/config.py`에 정의됨)
- **메모리 관리**: API 키는 사용 후 즉시 메모리에서 제거 (del, gc)
- **로그 마스킹**: API 키/시크릿은 로그에 절대 출력하지 않음

### 13.2 네트워크 보안

- **HTTPS Only**: 모든 거래소 REST API 호출은 HTTPS 필수
- **WSS Only**: 모든 거래소 WebSocket 연결은 WSS 필수
- **타임아웃**: 모든 HTTP 요청에 `EXCHANGE_HTTP_TIMEOUT` 적용
- **요청 서명**: 거래소별 HMAC 서명은 각 Provider 구현에서 처리

### 13.3 장애 격리

- **Circuit Breaker**: 거래소별 독립 → 한 거래소 장애가 다른 거래소에 영향 없음
- **Rate Limiter**: 사용자별 독립 → 한 사용자의 과다 요청이 다른 사용자에 영향 없음
- **Timeout**: 거래소 응답 지연 시 빠른 실패

---

## 14. 구현 시 주의사항

1. **기존 Rate Limiter 재사용**: `ExchangeRateLimiter`는 이미 완전히 구현됨. 새로 만들지 않고 `BaseExchangeProvider`에서 주입받아 사용.

2. **Circuit Breaker 인메모리**: v1-8은 단일 서버 환경이므로 인메모리로 충분. Redis 기반은 멀티 인스턴스 확장 시 고려 (키 패턴만 예약).

3. **Mock Provider 중요성**: v1-8에서 실제 거래소 구현은 없음. Mock Provider가 전체 흐름을 검증하는 유일한 수단.

4. **trading 패키지 독립성**: `trading/` 패키지는 `providers/` 인터페이스만 import. FastAPI, SQLAlchemy 등 프레임워크 의존성 금지.

5. **점진적 거래소 추가**: M3(Upbit), M5(CoinOne), M10(Coinbase), M11(Binance) 마일스톤에서 각 Provider를 구현. ABC 인터페이스 준수만 하면 Factory에 등록으로 즉시 사용 가능.

6. **WebSocket 재연결**: Exponential Backoff + 최대 재시도 횟수 제한. 기존 `ws/subscribers.py`의 패턴 참고.

7. **거래소 응답 정규화**: 각 거래소의 다른 응답 형식을 `types.py`의 공통 모델로 변환하는 것은 각 Provider 구현체의 책임.

---

---

## 15. 열거형 상세 (`providers/enums.py`)

```python
"""거래소 추상화 계층 열거형 타입 정의."""
from __future__ import annotations

from enum import StrEnum


class ExchangeType(StrEnum):
    """지원 거래소 식별자."""
    UPBIT = "upbit"
    COINONE = "coinone"
    COINBASE = "coinbase"
    BINANCE = "binance"


class OrderSide(StrEnum):
    """주문 방향."""
    BUY = "buy"
    SELL = "sell"


class OrderMethod(StrEnum):
    """주문 방식."""
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    """주문 상태 (TradeOrder.status와 동일한 값)."""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class ApiKeyPermission(StrEnum):
    """API 키 권한 종류 (거래소마다 표현 방식이 다르므로 정규화)."""
    VIEW_BALANCE = "view_balance"   # 잔고/자산 조회
    VIEW_ORDERS = "view_orders"     # 주문 내역 조회
    TRADE = "trade"                 # 주문 생성/취소
    WITHDRAW = "withdraw"           # 출금 (경고 대상)


class CircuitState(StrEnum):
    """Circuit Breaker 상태."""
    CLOSED = "closed"        # 정상 동작
    OPEN = "open"            # 차단 중 (거래소 장애 감지)
    HALF_OPEN = "half_open"  # 복구 시도 중
```

---

## 16. 데이터 모델 상세 (`providers/types.py`)

```python
"""거래소 추상화 계층 공통 Pydantic 데이터 모델."""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime

from pydantic import BaseModel

from .enums import ApiKeyPermission, ExchangeType, OrderMethod, OrderSide, OrderStatus


# ── 시세 / 호가 ─────────────────────────────────────────────────────────────


class Ticker(BaseModel):
    """실시간 시세 스냅샷."""
    exchange: ExchangeType
    symbol: str           # 정규화 심볼 e.g. "BTC/KRW"
    market: str           # 거래소 내부 마켓 코드 e.g. "KRW-BTC"
    price: Decimal        # 현재가
    open_price: Decimal   # 24h 시가
    high_price: Decimal   # 24h 고가
    low_price: Decimal    # 24h 저가
    volume: Decimal       # 24h 거래량 (코인)
    trade_value: Decimal  # 24h 거래대금 (KRW/USD)
    change_rate: Decimal  # 24h 변동률 (소수: 0.05 = +5%)
    timestamp: datetime   # 거래소 기준 타임스탬프 (UTC)


class OrderBookEntry(BaseModel):
    """단일 호가."""
    price: Decimal
    quantity: Decimal


class OrderBook(BaseModel):
    """호가창 스냅샷."""
    exchange: ExchangeType
    symbol: str
    market: str
    asks: list[OrderBookEntry]  # 매도 호가, 오름차순 (낮은 가격 먼저)
    bids: list[OrderBookEntry]  # 매수 호가, 내림차순 (높은 가격 먼저)
    timestamp: datetime


class Candle(BaseModel):
    """OHLCV 캔들 데이터."""
    exchange: ExchangeType
    symbol: str
    market: str
    timeframe: str    # "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    timestamp: datetime  # 캔들 시작 시각 (UTC)


# ── 주문 ─────────────────────────────────────────────────────────────────────


class Order(BaseModel):
    """주문 요청 모델 (Provider.place_order() 입력)."""
    market: str               # 거래소 내부 마켓 코드
    side: OrderSide
    method: OrderMethod
    quantity: Decimal         # 수량 (코인 기준)
    price: Decimal | None = None  # 지정가 주문 시 필수, 시장가 시 None


class OrderResult(BaseModel):
    """주문 실행 결과 모델 (Provider.place_order() 반환)."""
    exchange_order_id: str
    market: str
    side: OrderSide
    method: OrderMethod
    status: OrderStatus
    quantity: Decimal
    executed_quantity: Decimal = Decimal("0")
    price: Decimal | None = None              # 주문 가격 (지정가)
    avg_executed_price: Decimal | None = None # 평균 체결 가격
    fee: Decimal = Decimal("0")
    fee_currency: str | None = None           # e.g. "KRW", "BNB"
    created_at: datetime
    executed_at: datetime | None = None


# ── 잔고 / 수수료 / API 키 ────────────────────────────────────────────────────


class Balance(BaseModel):
    """단일 자산 잔고."""
    currency: str       # e.g. "KRW", "BTC", "ETH"
    available: Decimal  # 사용 가능 (미잠금)
    locked: Decimal     # 잠금 (주문 중)

    @property
    def total(self) -> Decimal:
        return self.available + self.locked


class TradingFee(BaseModel):
    """수수료 정보."""
    exchange: ExchangeType
    market: str
    maker_fee: Decimal   # 지정가 수수료율 (소수: 0.001 = 0.1%)
    taker_fee: Decimal   # 시장가 수수료율


class ApiKeyInfo(BaseModel):
    """API 키 유효성 및 권한 정보 (verify_api_key() 반환)."""
    exchange: ExchangeType
    permissions: list[ApiKeyPermission]
    is_valid: bool
    error_message: str | None = None  # is_valid=False 시 사유
    has_withdraw_permission: bool = False  # 출금 권한 경고 표시용


# ── 심볼 변환 ──────────────────────────────────────────────────────────────────


class SymbolMapper:
    """거래소별 마켓 코드 ↔ 정규화 심볼 양방향 변환.

    정규화 심볼 형식: "{BASE}/{QUOTE}"  e.g. "BTC/KRW", "ETH/USDT"
    구체 구현체(UpbitProvider 등)에서 _MAPS 에 거래소 심볼을 추가한다.
    """
    _MAPS: dict[ExchangeType, dict[str, str]] = {
        ExchangeType.UPBIT: {
            "BTC/KRW": "KRW-BTC",
            "ETH/KRW": "KRW-ETH",
            "XRP/KRW": "KRW-XRP",
        },
        ExchangeType.COINONE: {
            "BTC/KRW": "btc",
            "ETH/KRW": "eth",
        },
        ExchangeType.COINBASE: {
            "BTC/USDT": "BTC-USDT",
            "ETH/USDT": "ETH-USDT",
        },
        ExchangeType.BINANCE: {
            "BTC/USDT": "BTCUSDT",
            "ETH/USDT": "ETHUSDT",
        },
    }
    # 역방향 캐시 (클래스 로드 시 자동 생성)
    _REVERSE: dict[ExchangeType, dict[str, str]] = {}

    @classmethod
    def to_market(cls, exchange: ExchangeType, symbol: str) -> str:
        """정규화 심볼 → 거래소 마켓 코드.

        Raises:
            ExchangeInvalidSymbolError: 미지원 심볼
        """
        ...

    @classmethod
    def to_symbol(cls, exchange: ExchangeType, market: str) -> str:
        """거래소 마켓 코드 → 정규화 심볼.

        Raises:
            ExchangeInvalidSymbolError: 미지원 마켓 코드
        """
        ...
```

---

## 17. 예외 계층 상세 (`providers/exceptions.py` + `core/exceptions.py`)

### 17.1 providers/exceptions.py — Provider 내부 예외

```python
"""거래소 Provider 도메인 예외.

AppError와 독립적인 내부 예외 계층.
서비스 레이어에서 AppError(ExchangeErrors 팩토리)로 변환하여 클라이언트에 반환.
"""
from __future__ import annotations


class ExchangeError(Exception):
    """거래소 관련 기본 예외."""
    def __init__(
        self,
        exchange: str,
        message: str,
        original_error: Exception | None = None,
    ) -> None:
        self.exchange = exchange
        self.original_error = original_error
        super().__init__(f"[{exchange}] {message}")


class ExchangeAuthError(ExchangeError):
    """API 키 인증 실패 — 키/시크릿 불일치, 만료."""


class ExchangePermissionError(ExchangeError):
    """API 키 권한 부족 — 필요한 권한 미설정."""


class ExchangeRateLimitError(ExchangeError):
    """거래소 서버 측 Rate Limit 초과 (HTTP 429)."""
    def __init__(
        self,
        exchange: str,
        retry_after_seconds: int | None = None,
        original_error: Exception | None = None,
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(exchange, "Rate limit exceeded", original_error)


class ExchangeOrderError(ExchangeError):
    """주문 처리 실패 — 최소 주문 금액 미달, 잘못된 수량 등."""


class ExchangeInsufficientBalanceError(ExchangeOrderError):
    """잔고 부족으로 인한 주문 실패."""


class ExchangeNetworkError(ExchangeError):
    """네트워크 연결 오류 — 타임아웃, DNS 실패, SSL 오류."""


class ExchangeUnavailableError(ExchangeError):
    """서비스 불가 — Circuit Breaker OPEN 또는 거래소 점검."""


class ExchangeInvalidSymbolError(ExchangeError):
    """지원하지 않는 심볼 또는 마켓 코드."""


class ExchangeDataError(ExchangeError):
    """응답 데이터 파싱 실패 또는 예상치 못한 응답 형식."""
```

**HTTP 상태코드 → 예외 매핑 기준:**

| HTTP 상태 / 조건 | ExchangeError 서브클래스 |
|----------------|------------------------|
| 401 (인증 실패) | `ExchangeAuthError` |
| 403 (권한 없음) | `ExchangePermissionError` |
| 429 (Rate Limit) | `ExchangeRateLimitError` |
| 400 (잔고 부족 메시지) | `ExchangeInsufficientBalanceError` |
| 400 (기타 주문 오류) | `ExchangeOrderError` |
| 503 / 거래소 점검 | `ExchangeUnavailableError` |
| 타임아웃 / 연결 오류 | `ExchangeNetworkError` |
| 파싱 오류 | `ExchangeDataError` |
| CB OPEN 상태 | `ExchangeUnavailableError` |

**Circuit Breaker 제외 예외 (장애 카운트에서 제외 — 사용자 오류):**
- `ExchangeAuthError`, `ExchangePermissionError`, `ExchangeInvalidSymbolError`, `ExchangeInsufficientBalanceError`

### 17.2 core/exceptions.py — ExchangeErrors 추가

```python
class ExchangeErrors:
    """거래소 도메인 AppError 팩토리 (HTTP 응답용)."""

    @staticmethod
    def circuit_open(exchange: str) -> AppError:
        """Circuit Breaker OPEN 상태."""
        return AppError(
            "EXCHANGE_CIRCUIT_OPEN",
            f"{exchange} 거래소가 일시적으로 차단되었습니다. 잠시 후 재시도해주세요.",
            503,
        )

    @staticmethod
    def rate_limited(exchange: str, retry_after_seconds: int | None = None) -> AppError:
        """Rate Limit 초과."""
        msg = "거래소 요청 횟수 제한을 초과했습니다."
        if retry_after_seconds:
            msg += f" {retry_after_seconds}초 후 재시도해주세요."
        return AppError("EXCHANGE_RATE_LIMITED", msg, 429)

    @staticmethod
    def auth_failed(exchange: str) -> AppError:
        """API 키 인증 실패."""
        return AppError(
            "EXCHANGE_AUTH_FAILED",
            f"{exchange} API 키 인증에 실패했습니다. API 키와 시크릿을 확인해주세요.",
            401,
        )

    @staticmethod
    def permission_denied(exchange: str, missing: str) -> AppError:
        """API 키 권한 부족."""
        return AppError(
            "EXCHANGE_PERMISSION_DENIED",
            f"{exchange} API 키에 필요한 권한({missing})이 없습니다.",
            403,
        )

    @staticmethod
    def insufficient_balance() -> AppError:
        """잔고 부족."""
        return AppError("EXCHANGE_INSUFFICIENT_BALANCE", "잔고가 부족합니다.", 400)

    @staticmethod
    def order_failed(exchange: str, reason: str) -> AppError:
        """주문 실패."""
        return AppError("EXCHANGE_ORDER_FAILED", f"주문 처리 실패: {reason}", 400)

    @staticmethod
    def unavailable(exchange: str) -> AppError:
        """거래소 서비스 불가."""
        return AppError(
            "EXCHANGE_UNAVAILABLE",
            f"{exchange} 거래소에 연결할 수 없습니다. 잠시 후 재시도해주세요.",
            503,
        )

    @staticmethod
    def invalid_api_key() -> AppError:
        """유효하지 않은 API 키."""
        return AppError("EXCHANGE_INVALID_API_KEY", "유효하지 않은 API 키입니다.", 422)

    @staticmethod
    def account_not_found() -> AppError:
        """거래소 계정 미등록."""
        return AppError(
            "EXCHANGE_ACCOUNT_NOT_FOUND", "거래소 계정이 등록되지 않았습니다.", 404
        )
```

---

## 18. ABC 추상 메서드 계약 상세 (`providers/base.py`)

```python
"""거래소 추상 클래스 정의."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from .enums import ExchangeType
from .types import (
    ApiKeyInfo, Balance, Candle, Order,
    OrderBook, OrderResult, Ticker, TradingFee,
)


class ExchangeRestProvider(ABC):
    """거래소 REST API 추상 계층.

    계약(Contract):
    - 모든 메서드는 async여야 함
    - 거래소 응답을 providers/types.py의 공통 모델로 정규화하여 반환
    - 거래소 고유 예외를 providers/exceptions.py 계층으로 변환
    - 인증 정보(api_key, api_secret)는 __init__에서 주입받아 인스턴스 변수로 보관
    """

    @abstractmethod
    async def get_ticker(self, market: str) -> Ticker:
        """현재 시세 조회.

        Args:
            market: 거래소 내부 마켓 코드 (SymbolMapper.to_market() 변환 후 전달)

        Raises:
            ExchangeInvalidSymbolError: 미지원 마켓
            ExchangeNetworkError: 연결 오류
            ExchangeUnavailableError: Circuit Breaker OPEN
        """

    @abstractmethod
    async def get_orderbook(self, market: str, depth: int = 10) -> OrderBook:
        """호가창 조회.

        Args:
            market: 거래소 내부 마켓 코드
            depth: 조회할 호가 개수 (기본 10)
        """

    @abstractmethod
    async def get_candles(
        self, market: str, timeframe: str, count: int = 200
    ) -> list[Candle]:
        """OHLCV 캔들 데이터 조회.

        Args:
            market: 거래소 내부 마켓 코드
            timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
            count: 조회할 캔들 개수 (기본 200)

        Returns:
            list[Candle]: 최신순 정렬 (index 0 = 가장 최신 캔들)
        """

    @abstractmethod
    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행.

        Raises:
            ExchangeAuthError: API 키 인증 실패
            ExchangePermissionError: TRADE 권한 없음
            ExchangeInsufficientBalanceError: 잔고 부족
            ExchangeOrderError: 최소 주문 금액 미달 등
            ExchangeNetworkError, ExchangeUnavailableError
        """

    @abstractmethod
    async def cancel_order(self, market: str, exchange_order_id: str) -> bool:
        """주문 취소.

        Returns:
            bool: 취소 성공 여부 (이미 체결된 주문은 False)
        """

    @abstractmethod
    async def get_balance(self) -> list[Balance]:
        """전체 잔고 조회.

        Returns:
            list[Balance]: 보유 자산 목록 (잔고 0인 자산 포함 여부는 거래소마다 상이)
        """

    @abstractmethod
    async def get_trading_fee(self, market: str) -> TradingFee:
        """수수료 조회."""

    @abstractmethod
    async def verify_api_key(self) -> ApiKeyInfo:
        """API 키 유효성 및 권한 검증.

        Returns:
            ApiKeyInfo: is_valid=True/False + permissions 목록 + error_message
            예외 대신 ApiKeyInfo로 결과 반환 (네트워크 오류만 예외)

        Raises:
            ExchangeNetworkError: 검증 자체 불가한 오류만
        """


class ExchangeStreamProvider(ABC):
    """거래소 WebSocket 스트림 추상 계층.

    계약(Contract):
    - connect() 호출 후에만 subscribe_* 가능
    - 연결 끊김 시 자동 재연결 (Exponential Backoff, 최대 EXCHANGE_WS_RECONNECT_MAX회)
    - disconnect() 호출 시 모든 구독 자동 해제
    """

    @abstractmethod
    async def connect(self) -> None:
        """WebSocket 연결 수립.

        Raises:
            ExchangeNetworkError: 연결 실패
            ExchangeUnavailableError: Circuit Breaker OPEN
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """WebSocket 연결 종료 및 구독 정리."""

    @abstractmethod
    async def subscribe_ticker(
        self,
        markets: list[str],
        callback: Callable[[Ticker], Awaitable[None]],
    ) -> None:
        """실시간 시세 구독.

        Args:
            markets: 거래소 내부 마켓 코드 목록
            callback: 시세 수신 시 호출할 async 콜백
        """

    @abstractmethod
    async def subscribe_orderbook(
        self,
        markets: list[str],
        callback: Callable[[OrderBook], Awaitable[None]],
    ) -> None:
        """실시간 호가창 구독."""

    @abstractmethod
    async def unsubscribe(self, markets: list[str] | None = None) -> None:
        """구독 해제.

        Args:
            markets: 해제할 마켓 목록. None 시 전체 해제.
        """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """WebSocket 연결 상태."""


class ExchangeProvider(ExchangeRestProvider, ExchangeStreamProvider):
    """REST + Stream 통합 추상 클래스. 모든 거래소 구현체의 최상위 타입."""

    @property
    @abstractmethod
    def exchange_type(self) -> ExchangeType:
        """거래소 식별자."""

    @abstractmethod
    async def initialize(self) -> None:
        """Provider 초기화 (lifespan startup 에서 호출).

        HTTP 클라이언트 초기화, API 키 사전 검증 등.
        """

    @abstractmethod
    async def close(self) -> None:
        """리소스 정리 (lifespan shutdown 에서 호출).

        HTTP 클라이언트 종료, WebSocket 연결 해제.
        """
```

---

## 19. Circuit Breaker 코드 상세 (`providers/circuit_breaker.py`)

```python
"""Circuit Breaker 구현 — 거래소 장애 감지 및 차단."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from .enums import CircuitState
from .exceptions import ExchangeUnavailableError

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class CircuitBreakerConfig:
    """Circuit Breaker 설정값 (섹션 4.2 기준)."""
    failure_threshold: int = 5
    """연속 실패 허용 횟수 (CLOSED → OPEN 전환)."""

    failure_rate_threshold: float = 0.5
    """실패율 임계값 (50%). window 내 실패율이 이를 초과하면 OPEN."""

    failure_rate_window: int = 30
    """실패율 측정 윈도우 (초). 최소 5개 샘플 이상 시 실패율 체크."""

    recovery_timeout: int = 60
    """OPEN 상태 유지 시간 (초). 경과 후 HALF_OPEN으로 자동 전환."""

    half_open_max_calls: int = 1
    """HALF_OPEN에서 허용할 최대 시험 호출 수."""

    excluded_exceptions: tuple[type[Exception], ...] = field(default_factory=tuple)
    """서킷 카운트에서 제외할 예외 (사용자 오류: Auth, Permission, InvalidSymbol 등)."""


class CircuitBreaker:
    """단일 거래소에 대한 Circuit Breaker.

    asyncio.Lock으로 상태 전환 보호 (asyncio 단일 이벤트 루프 전제).
    슬라이딩 윈도우 방식: 연속 실패 OR 실패율 초과 시 OPEN 전환.
    """

    def __init__(self, name: str, config: CircuitBreakerConfig) -> None:
        self._name = name
        self._config = config
        self._state = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._half_open_calls: int = 0
        self._opened_at: float | None = None
        # 슬라이딩 윈도우: (monotonic_timestamp, success: bool)
        self._window: deque[tuple[float, bool]] = deque()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._consecutive_failures

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: object,
        **kwargs: object,
    ) -> T:
        """Circuit Breaker를 통한 async 함수 호출.

        Raises:
            ExchangeUnavailableError: OPEN 상태 (차단 중)
        """
        async with self._lock:
            # OPEN → HALF_OPEN 전환 체크
            if (
                self._state == CircuitState.OPEN
                and self._opened_at is not None
                and time.monotonic() - self._opened_at >= self._config.recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("CircuitBreaker[%s] OPEN → HALF_OPEN", self._name)

            if self._state == CircuitState.OPEN:
                raise ExchangeUnavailableError(
                    self._name,
                    f"Circuit breaker is OPEN for {self._name}.",
                )

            if (
                self._state == CircuitState.HALF_OPEN
                and self._half_open_calls >= self._config.half_open_max_calls
            ):
                raise ExchangeUnavailableError(
                    self._name,
                    f"Circuit breaker HALF_OPEN: max probe calls reached for {self._name}.",
                )

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            await self._record(success=True)
            return result
        except Exception as exc:
            if not isinstance(exc, self._config.excluded_exceptions):
                await self._record(success=False)
            raise

    async def _record(self, *, success: bool) -> None:
        now = time.monotonic()
        async with self._lock:
            self._window.append((now, success))
            cutoff = now - self._config.failure_rate_window
            while self._window and self._window[0][0] < cutoff:
                self._window.popleft()

            if success:
                self._consecutive_failures = 0
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.CLOSED
                    logger.info("CircuitBreaker[%s] HALF_OPEN → CLOSED (recovered)", self._name)
            else:
                self._consecutive_failures += 1
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.OPEN
                    self._opened_at = now
                    logger.warning("CircuitBreaker[%s] HALF_OPEN → OPEN", self._name)
                elif self._state == CircuitState.CLOSED and self._should_open():
                    self._state = CircuitState.OPEN
                    self._opened_at = now
                    logger.warning(
                        "CircuitBreaker[%s] CLOSED → OPEN (failures=%d)",
                        self._name, self._consecutive_failures,
                    )

    def _should_open(self) -> bool:
        """연속 실패 OR 실패율 초과 시 True."""
        if self._consecutive_failures >= self._config.failure_threshold:
            return True
        if len(self._window) >= 5:  # 최소 5개 샘플
            failed = sum(1 for _, ok in self._window if not ok)
            if failed / len(self._window) >= self._config.failure_rate_threshold:
                return True
        return False

    def reset(self) -> None:
        """강제 초기화 (테스트 및 수동 복구용)."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_calls = 0
        self._opened_at = None
        self._window.clear()
```

---

## 20. Factory + Registry 코드 상세 (`providers/factory.py`)

```python
"""거래소 Provider Factory + Registry."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from redis.asyncio import Redis

from app.core.encryption import decrypt_value
from app.core.rate_limiter import ExchangeRateLimiter
from app.models.exchange import UserExchangeAccount

from .base import ExchangeProvider
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .enums import ExchangeType
from .exceptions import (
    ExchangeAuthError,
    ExchangeInsufficientBalanceError,
    ExchangeInvalidSymbolError,
    ExchangePermissionError,
)

logger = logging.getLogger(__name__)
P = TypeVar("P", bound=ExchangeProvider)

# ── 거래소별 Circuit Breaker 기본 설정 ─────────────────────────────────────────

_EXCLUDED_FROM_CB = (
    ExchangeAuthError,
    ExchangePermissionError,
    ExchangeInvalidSymbolError,
    ExchangeInsufficientBalanceError,
)

CIRCUIT_BREAKER_CONFIGS: dict[str, CircuitBreakerConfig] = {
    "upbit": CircuitBreakerConfig(
        failure_threshold=5, failure_rate_threshold=0.5, failure_rate_window=30,
        recovery_timeout=60, half_open_max_calls=1, excluded_exceptions=_EXCLUDED_FROM_CB,
    ),
    "coinone": CircuitBreakerConfig(
        failure_threshold=5, failure_rate_threshold=0.5, failure_rate_window=30,
        recovery_timeout=60, half_open_max_calls=1, excluded_exceptions=_EXCLUDED_FROM_CB,
    ),
    "coinbase": CircuitBreakerConfig(
        failure_threshold=5, failure_rate_threshold=0.5, failure_rate_window=30,
        recovery_timeout=30, half_open_max_calls=1, excluded_exceptions=_EXCLUDED_FROM_CB,
    ),
    "binance": CircuitBreakerConfig(
        failure_threshold=5, failure_rate_threshold=0.5, failure_rate_window=30,
        recovery_timeout=30, half_open_max_calls=1, excluded_exceptions=_EXCLUDED_FROM_CB,
    ),
}


# ── Registry ──────────────────────────────────────────────────────────────────


class ExchangeProviderRegistry:
    """등록된 Provider 클래스 관리 레지스트리 (클래스 변수 전역 관리)."""

    _registry: dict[ExchangeType, type[ExchangeProvider]] = {}

    @classmethod
    def register(cls, exchange_type: ExchangeType) -> Callable[[type[P]], type[P]]:
        """클래스 데코레이터 방식 Provider 등록.

        Example:
            @ExchangeProviderRegistry.register(ExchangeType.UPBIT)
            class UpbitProvider(BaseExchangeProvider):
                ...
        """
        def decorator(provider_cls: type[P]) -> type[P]:
            cls._registry[exchange_type] = provider_cls
            logger.debug("Registered provider: %s → %s", exchange_type, provider_cls.__name__)
            return provider_cls
        return decorator

    @classmethod
    def get(cls, exchange_type: ExchangeType) -> type[ExchangeProvider]:
        """Raises:
            KeyError: 등록되지 않은 거래소
        """
        if exchange_type not in cls._registry:
            raise KeyError(f"No provider registered for exchange: {exchange_type}")
        return cls._registry[exchange_type]

    @classmethod
    def registered_exchanges(cls) -> list[ExchangeType]:
        return list(cls._registry.keys())


# ── Factory ───────────────────────────────────────────────────────────────────


class ExchangeProviderFactory:
    """싱글턴 Factory — Circuit Breaker + Rate Limiter 주입 Provider 생성.

    Circuit Breaker는 거래소별로 공유 (장애 상태 서버 전체에서 유지).
    """

    _instance: ExchangeProviderFactory | None = None

    def __init__(self, redis: Redis) -> None:
        self._rate_limiter = ExchangeRateLimiter(redis)
        self._circuit_breakers: dict[ExchangeType, CircuitBreaker] = {
            ExchangeType(name): CircuitBreaker(name=name, config=cfg)
            for name, cfg in CIRCUIT_BREAKER_CONFIGS.items()
        }
        self._active_providers: list[ExchangeProvider] = []

    @classmethod
    def instance(cls) -> ExchangeProviderFactory:
        """싱글턴 인스턴스 반환."""
        if cls._instance is None:
            raise RuntimeError("ExchangeProviderFactory not initialized.")
        return cls._instance

    @classmethod
    def init(cls, redis: Redis) -> ExchangeProviderFactory:
        """싱글턴 초기화 — lifespan startup에서 1회 호출."""
        cls._instance = cls(redis)
        return cls._instance

    def register_defaults(self) -> None:
        """Mock Provider로 모든 거래소 기본 등록.

        실제 거래소 구현체는 M3+(Upbit) 마일스톤에서 교체 등록.
        """
        from .mock_provider import MockExchangeProvider
        for exchange_type in ExchangeType:
            if exchange_type not in ExchangeProviderRegistry._registry:
                ExchangeProviderRegistry._registry[exchange_type] = MockExchangeProvider

    def create(
        self,
        exchange_type: ExchangeType,
        api_key: str,
        api_secret: str,
        user_id: str,
    ) -> ExchangeProvider:
        """평문 API 키로 Provider 인스턴스 생성.

        Raises:
            KeyError: 등록되지 않은 거래소
        """
        provider_cls = ExchangeProviderRegistry.get(exchange_type)
        cb = self._circuit_breakers[exchange_type]
        provider = provider_cls(
            exchange_type=exchange_type,
            api_key=api_key,
            api_secret=api_secret,
            rate_limiter=self._rate_limiter,
            circuit_breaker=cb,
            user_id=user_id,
        )
        self._active_providers.append(provider)
        return provider

    async def create_from_account(
        self,
        account: UserExchangeAccount,
        encryption_key: bytes,
    ) -> ExchangeProvider:
        """DB의 UserExchangeAccount에서 복호화 후 Provider 생성.

        Raises:
            KeyError: 등록되지 않은 거래소
            ValueError: 복호화 실패
        """
        api_key = decrypt_value(account.api_key_encrypted, encryption_key)
        api_secret = decrypt_value(account.api_secret_encrypted, encryption_key)
        return self.create(
            exchange_type=ExchangeType(account.exchange_type),
            api_key=api_key,
            api_secret=api_secret,
            user_id=str(account.user_id),
        )

    def get_circuit_breaker(self, exchange_type: ExchangeType) -> CircuitBreaker:
        """거래소별 Circuit Breaker 조회 (헬스체크/모니터링용)."""
        return self._circuit_breakers[exchange_type]

    async def close_all(self) -> None:
        """모든 활성 Provider 정리 — lifespan shutdown에서 호출."""
        for provider in self._active_providers:
            try:
                await provider.close()
            except Exception:
                logger.exception("Error closing provider: %s", provider.exchange_type)
        self._active_providers.clear()
        ExchangeProviderFactory._instance = None
```

---

## 21. Base Implementation 상세 (`providers/base_impl.py`)

```python
"""거래소 Provider 공통 기반 구현체 — Rate Limiter + Circuit Breaker 주입."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from app.core.rate_limiter import ExchangeRateLimiter, RateLimitResult

from .base import ExchangeProvider
from .circuit_breaker import CircuitBreaker
from .exceptions import ExchangeRateLimitError
from .enums import ExchangeType

logger = logging.getLogger(__name__)
T = TypeVar("T")


class BaseExchangeProvider(ExchangeProvider):
    """공통 HTTP/WS 클라이언트 + Rate Limiter + Circuit Breaker 통합 기반 클래스.

    구체 거래소 구현체는 이 클래스를 상속하고 추상 메서드를 구현한다.
    모든 REST 호출은 `_execute_rest()` 래퍼를 통해야 한다.
    """

    def __init__(
        self,
        exchange_type: ExchangeType,
        api_key: str,
        api_secret: str,
        rate_limiter: ExchangeRateLimiter,
        circuit_breaker: CircuitBreaker,
        user_id: str,
    ) -> None:
        self._exchange_type = exchange_type
        self._api_key = api_key
        self._api_secret = api_secret
        self._rate_limiter = rate_limiter
        self._circuit_breaker = circuit_breaker
        self._user_id = user_id
        self._http_client: httpx.AsyncClient | None = None
        self._ws_connected: bool = False

    @property
    def exchange_type(self) -> ExchangeType:
        return self._exchange_type

    @property
    def is_connected(self) -> bool:
        return self._ws_connected

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy init httpx 클라이언트 (HTTP/1.1 Keep-Alive 재사용)."""
        if self._http_client is None or self._http_client.is_closed:
            from app.core.config import settings
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=float(settings.EXCHANGE_HTTP_TIMEOUT),
                    write=5.0,
                    pool=5.0,
                ),
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                ),
            )
        return self._http_client

    async def _execute_rest(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Rate Limiter → Circuit Breaker 순서로 REST 호출 래핑.

        1. Rate Limit 확인 (초과 시 ExchangeRateLimitError)
        2. Circuit Breaker를 통한 func 호출
        """
        rate_result: RateLimitResult = await self._rate_limiter.acquire(
            self._exchange_type.value, self._user_id
        )
        if not rate_result.allowed:
            raise ExchangeRateLimitError(
                self._exchange_type.value,
                retry_after_seconds=rate_result.retry_after_ms // 1000,
            )
        return await self._circuit_breaker.call(func, *args, **kwargs)

    async def initialize(self) -> None:
        """기본 초기화 — HTTP 클라이언트 준비."""
        await self._get_http_client()

    async def close(self) -> None:
        """기본 정리 — HTTP 클라이언트 종료 + WS 연결 해제."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        if self._ws_connected:
            await self.disconnect()
```

---

## 22. `providers/__init__.py` Public API

```python
"""providers 패키지 Public API.

외부 (services/, ws/, tasks/, trading/) 에서는 이 __init__.py를 통해서만 import.
providers 내부 모듈 직접 import 금지.
"""
from .base import ExchangeProvider, ExchangeRestProvider, ExchangeStreamProvider
from .base_impl import BaseExchangeProvider
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .enums import (
    ApiKeyPermission,
    CircuitState,
    ExchangeType,
    OrderMethod,
    OrderSide,
    OrderStatus,
)
from .exceptions import (
    ExchangeAuthError,
    ExchangeDataError,
    ExchangeError,
    ExchangeInsufficientBalanceError,
    ExchangeInvalidSymbolError,
    ExchangeNetworkError,
    ExchangeOrderError,
    ExchangePermissionError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from .factory import ExchangeProviderFactory, ExchangeProviderRegistry
from .types import (
    ApiKeyInfo,
    Balance,
    Candle,
    Order,
    OrderBook,
    OrderBookEntry,
    OrderResult,
    SymbolMapper,
    Ticker,
    TradingFee,
)

__all__ = [
    # Base classes
    "ExchangeProvider", "ExchangeRestProvider", "ExchangeStreamProvider",
    "BaseExchangeProvider",
    # Factory
    "ExchangeProviderFactory", "ExchangeProviderRegistry",
    # Circuit Breaker
    "CircuitBreaker", "CircuitBreakerConfig", "CircuitState",
    # Enums
    "ExchangeType", "OrderSide", "OrderMethod", "OrderStatus", "ApiKeyPermission",
    # Types
    "Ticker", "OrderBook", "OrderBookEntry", "Candle",
    "Order", "OrderResult", "Balance", "TradingFee", "ApiKeyInfo", "SymbolMapper",
    # Exceptions
    "ExchangeError", "ExchangeAuthError", "ExchangePermissionError",
    "ExchangeRateLimitError", "ExchangeOrderError", "ExchangeInsufficientBalanceError",
    "ExchangeNetworkError", "ExchangeUnavailableError",
    "ExchangeInvalidSymbolError", "ExchangeDataError",
]
```

---

## 23. DI 연동 상세 (`core/deps.py` 추가)

```python
# core/deps.py 추가 내용

from typing import Annotated
from fastapi import Depends
from app.providers.factory import ExchangeProviderFactory


def get_exchange_factory() -> ExchangeProviderFactory:
    """앱 시작 시 초기화된 싱글턴 Factory 반환."""
    return ExchangeProviderFactory.instance()


ExchangeFactoryDep = Annotated[ExchangeProviderFactory, Depends(get_exchange_factory)]
```

**main.py lifespan 확장 (기존 구조 유지):**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 기존 DB/Redis 초기화 ...

    # Exchange Provider Factory 초기화 + 기본 등록
    factory = ExchangeProviderFactory.init(redis=redis_client)
    factory.register_defaults()

    yield

    # Exchange Provider 정리
    await factory.close_all()

    # ... 기존 DB/Redis 종료 ...
```

---

*코드 레벨 설계: code-architect (섹션 15–23) / 시스템 아키텍처: project-architect (섹션 1–14)*
