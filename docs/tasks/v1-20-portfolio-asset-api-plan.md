# v1-20: 포트폴리오/자산 조회 API 구현 설계서

> **태스크**: v1:20
> **브랜치**: `feature/v1-20_portfolio-asset-api`
> **작성**: project-architect + code-architect
> **최종 갱신**: 2026-03-15

---

## 1. 현재 상태 (프로젝트 컨텍스트)

### 활용 가능한 기존 인프라

| 컴포넌트 | 위치 | 역할 |
|----------|------|------|
| ExchangeProvider.get_balance() | `providers/base.py` | 거래소별 보유 자산 조회 → `Balance[]` |
| ExchangeProviderFactory | `providers/factory.py` | 싱글턴, `create_from_account()` |
| MarketCacheService.get_ticker() | `services/market_cache_service.py` | Redis 캐시된 실시간 시세 |
| OrderRepository | `repositories/order_repository.py` | TradeOrder CRUD, 주문 이력 |
| ExchangeAccountRepository | `repositories/exchange_account_repository.py` | 사용자 거래소 계정 조회 |
| TradeLog (MongoDB) | `documents/trading_logs.py` | 청산된 포지션 PnL 기록 |
| RedisKey / RedisTTL | `core/redis_keys.py` | 키 패턴, TTL 상수 |
| DailyPnlReport (MongoDB) | `documents/trading_logs.py` | 일별 PnL 리포트 (누적 통계) |

### 기존 모델/타입 참조

- `Balance(currency, available, locked)` — `providers/types.py:98`
- `Ticker(exchange, symbol, market, price, ...)` — `providers/types.py:15`
- `TradeOrder(price, quantity, executed_price, executed_quantity, fee, status, is_ai_order)` — `models/trading.py:119`
- `UserExchangeAccount(exchange_type, api_key_encrypted, ...)` — `models/exchange.py:22`
- `SymbolMapper.to_symbol(exchange, market)` — `providers/types.py:209`

---

## 2. 아키텍처 결정 사항

### ADR-020-1: 평균 매입가 계산 방식

**상태**: 승인됨
**맥락**: PRD에서 가중 평균과 FIFO 두 가지 언급. 구현 복잡도와 정확도 트레이드오프.
**선택지**:
1. 가중 평균 (VWAP): `Σ(executed_quantity × executed_price) / Σ(executed_quantity)`
2. FIFO: 매수 순서대로 매칭, 부분 체결 추적 필요

**결정**: **가중 평균 (VWAP)** 방식 채택
**근거**:
- 단일 SQL 집계 쿼리로 계산 가능 (성능 우수)
- FIFO는 매도 시 매수 이력 소비 추적이 필요하여 별도 테이블/상태 관리 필요
- 국내 거래소(업비트, 코인원)의 평균 매입가 표시도 가중 평균 방식
- 추후 FIFO 필요 시 별도 고도화 (v2)

**영향**: PortfolioRepository 집계 쿼리, PnL 계산 로직

### ADR-020-2: 포트폴리오 데이터 소스 전략

**상태**: 승인됨
**맥락**: 보유 자산은 거래소 API에서 실시간 조회 vs DB 동기화 후 DB에서 조회
**선택지**:
1. 거래소 API 실시간 호출 + Redis 캐시
2. 주기적 DB 동기화 (Celery) + DB 조회

**결정**: **거래소 API 실시간 호출 + Redis 캐시 (1분 TTL)**
**근거**:
- DB 동기화는 정합성 지연 문제 (입출금, 외부 거래 반영 불가)
- 거래소 API 호출은 Rate Limit 내 충분 (잔고 조회 1건/분)
- Redis 캐시로 중복 호출 방지
- v2에서 WS 기반 실시간 업데이트 가능

**영향**: PortfolioService 데이터 수집 흐름, Redis 캐시 전략

### ADR-020-3: 서비스 구조

**상태**: 승인됨
**맥락**: 포트폴리오 조회에 필요한 데이터 소스가 다양 (거래소 API, Redis, PG, MongoDB)
**결정**: **단일 PortfolioService** + **PortfolioRepository** 분리 (ReadOnly)
- PortfolioService: 오케스트레이션 (잔고 수집, 시세 조회, PnL 계산, 캐시 관리)
- PortfolioRepository: 평균 매입가 집계 쿼리 전담 (TradeOrder 테이블 SELECT 전용, Write 없음)
- PnL 계산 로직은 서비스 내 순수 함수 (`_calculate_coin_pnl`)로 분리

**영향**: 새 파일 2개 (service + repository), deps.py DI 추가

### ADR-020-4: 원화 환산

**상태**: 승인됨
**맥락**: 현재 지원 거래소(Upbit, CoinOne)는 모두 KRW 기축
**결정**: **KRW 직접 계산** (환율 변환 불필요)
- `current_price(KRW) × quantity = 원화 환산 가치`
- 향후 해외 거래소(Coinbase, Binance) 추가 시 USDT/USD → KRW 환율 서비스 신규 구현 (v2)
- 현재는 KRW 기축 코인만 대상이므로 별도 환율 모듈 미생성

**영향**: ST5 (원화 환율 변환) 범위 축소 — KRW 직접 곱셈만 수행

### ADR-020-5: 캐싱 전략

**상태**: 승인됨
**결정**:
- **포트폴리오 요약**: Redis JSON, 5분 TTL (`portfolio:summary:{user_id}`)
- **거래소별 상세**: Redis JSON, 1분 TTL (`portfolio:exchange:{user_id}:{exchange_account_id}`)
- **현재 시세**: 기존 ticker 캐시 재사용 (10초 TTL, `ticker:{exchange}:{market}`)
- **평균 매입가**: Redis JSON, 10분 TTL (`portfolio:avg_price:{user_id}:{exchange_account_id}`)
  - 주문 체결 시 무효화 (OrderService에서 DEL)

**Redis 키에 user_id 포함 근거**: keyspace 격리 명확, 보안 스캔 용이, 기존 `portfolio:summary` 패턴 일관성

### ADR-020-6: 도넛 차트 데이터 포맷

**상태**: 승인됨
**맥락**: 클라이언트에서 자산 비중 도넛 차트를 표시해야 함
**결정**: **API 응답에 `portfolio_weight` 필드 포함** (서버 사이드 계산)
- 각 코인의 `portfolio_weight` (소수점 2자리, 0.0~100.0 범위 Decimal) 제공
- KRW 현금 잔고도 별도 항목으로 포함 (symbol="KRW")
- 상위 5개 코인 + "기타" 그룹핑은 클라이언트에서 처리
- 전체 합이 100%가 되도록 마지막 항목에서 반올림 오차 보정 (remainder adjustment)

---

## 3. 데이터 흐름도

### 3.1 전체 자산 요약 (GET /api/v1/portfolio)

```
Client
  |
  v
API Layer (portfolio.py)
  |
  v
PortfolioService.get_portfolio_summary(user_id)
  |
  +--1 Redis 캐시 확인 -- HIT -> 즉시 반환
  |
  +--2 ExchangeAccountRepo.get_by_user_id(user_id)
  |     -> [UserExchangeAccount, ...]
  |
  +--3 거래소별 병렬 수집 (asyncio.gather)
  |     |
  |     +-- ExchangeProvider.get_balance()
  |     |    -> [Balance(currency, available, locked), ...]
  |     |    -> Redis 캐시 저장 (1분 TTL)
  |     |
  |     +-- MarketCacheService.get_ticker(exchange, market)
  |     |    -> Ticker.price (현재가)
  |     |    -> 캐시 MISS 시 Provider.get_ticker() fallback
  |     |
  |     +-- PortfolioRepository.get_avg_entry_prices(user_id, exchange_account_id)
  |          -> {coin_id: avg_price}
  |
  +--4 PnL 계산 (순수 함수)
  |     pnl = (current_price - avg_price) * quantity
  |     pnl_ratio = (current_price - avg_price) / avg_price * 100
  |
  +--5 AI / 수동 분리 집계
  |     PortfolioRepository.get_trade_stats(user_id) -> 거래 횟수
  |
  +--6 Redis 캐시 저장 (5분 TTL)
  |
  +--7 PortfolioSummaryResponse 반환
```

### 3.2 거래소별 상세 (GET /api/v1/portfolio/{exchange_account_id})

```
Client
  |
  v
API Layer (portfolio.py)
  |
  v
PortfolioService.get_exchange_portfolio(user_id, exchange_account_id)
  |
  +--1 소유권 검증 (ExchangeAccountRepo)
  |     account.user_id != user_id -> PortfolioErrors.exchange_account_not_owned()
  |
  +--2 Redis 캐시 확인 (portfolio:exchange:{user_id}:{ea_id})
  |     HIT -> 즉시 반환
  |
  +--3 거래소 잔고 수집
  |     Provider.get_balance() -> Balance[]
  |
  +--4 코인별 시세 + 평균 매입가 조회 (병렬)
  |     MarketCacheService.get_ticker() (각 코인)
  |     PortfolioRepository.get_avg_entry_prices()
  |
  +--5 PnL 계산 + 비중(weight) 계산
  |     portfolio_weight = coin_value / total_value * 100
  |
  +--6 Redis 캐시 저장 (1분 TTL)
  |
  +--7 ExchangePortfolioResponse 반환
```

### 3.3 캐시 무효화 흐름

```
주문 체결 (OrderService, status -> filled)
  |
  +-- DEL portfolio:avg_price:{user_id}:{exchange_account_id}
  +-- DEL portfolio:summary:{user_id}
  +-- DEL portfolio:exchange:{user_id}:{exchange_account_id}
```

---

## 4. 구현 파일 목록

### 4.1 신규 생성 파일

| 파일 | 역할 |
|------|------|
| `server/app/schemas/portfolio.py` | 포트폴리오 요청/응답 Pydantic 스키마 |
| `server/app/repositories/portfolio_repository.py` | 평균 매입가 집계 SQL 쿼리 (ReadOnly) |
| `server/app/services/portfolio_service.py` | 포트폴리오 비즈니스 로직 + 캐시 관리 |
| `server/app/api/v1/portfolio.py` | REST API 엔드포인트 |
| `server/tests/unit/test_portfolio_service.py` | 서비스 단위 테스트 |
| `server/tests/unit/test_portfolio_repository.py` | 리포지토리 단위 테스트 |
| `server/tests/integration/test_portfolio_api.py` | API 통합 테스트 |

### 4.2 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `server/app/core/redis_keys.py` | RedisKey.portfolio_summary(), portfolio_exchange(), portfolio_avg_price() + RedisTTL 상수 추가 |
| `server/app/core/deps.py` | get_portfolio_repository(), get_portfolio_service(), PortfolioRepoDep, PortfolioServiceDep |
| `server/app/core/exceptions.py` | PortfolioErrors 팩토리 클래스 추가 (4개 메서드) |
| `server/app/api/v1/__init__.py` | portfolio_router include 추가 (기존 라우터 등록 패턴 따름, main.py 수정 불필요) |

---

## 5. 컴포넌트 상세 설계

### 5.1 Pydantic 스키마 (`schemas/portfolio.py`)

```python
"""포트폴리오/자산 조회 API 스키마."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# -- 내부 데이터 타입 (서비스 계층) -----------------------------------------------

class AvgEntryPrice(BaseModel):
    """코인별 평균 매입가 + 총 매수 수량."""
    avg_price: Decimal
    total_buy_quantity: Decimal


class TradeCounts(BaseModel):
    """거래 횟수 통계."""
    total: int
    ai_count: int
    manual_count: int


# -- 응답 서브 모델 ---------------------------------------------------------------

class CoinHolding(BaseModel):
    """단일 코인 보유 현황."""
    symbol: str                            # e.g. "BTC/KRW"
    currency: str                          # e.g. "BTC" — Balance.currency 그대로
    quantity: Decimal                       # 총 보유 수량 (available + locked)
    available: Decimal                     # 사용 가능
    locked: Decimal                        # 주문 잠금
    avg_entry_price: Decimal | None        # 체결 주문 없으면 None (외부 입금)
    current_price: Decimal | None          # Redis ticker 없으면 None
    value_krw: Decimal | None              # current_price * quantity
    pnl_amount: Decimal | None             # 미실현 평가손익
    pnl_ratio: Decimal | None              # 수익률 % (e.g. 2.94 = +2.94%)
    weight_percent: Decimal | None         # 총자산 대비 비중 0.0~100.0, 소수점 2자리


class ExchangeSummary(BaseModel):
    """거래소별 요약 (by_exchange 항목)."""
    exchange_account_id: uuid.UUID
    exchange_type: str                     # "upbit" | "coinone"
    nickname: str | None                   # UserExchangeAccount.nickname 그대로
    balance_krw: Decimal | None            # 원화 환산 총자산
    pnl_amount: Decimal | None
    pnl_ratio: Decimal | None


class TopCoin(BaseModel):
    """전체 포트폴리오 상위 코인 (top_coins 항목)."""
    symbol: str                            # "BTC/KRW" — CoinResponse.symbol 패턴
    exchange_type: str
    quantity: Decimal
    avg_price: Decimal | None
    current_price: Decimal | None
    pnl_amount: Decimal | None


# -- 메인 응답 스키마 -------------------------------------------------------------

class PortfolioSummaryResponse(BaseModel):
    """GET /api/v1/portfolio 응답."""
    total_balance_krw: Decimal | None      # 전 거래소 합산 원화 환산 총자산
    total_pnl_amount: Decimal | None       # 합산 평가손익
    total_pnl_ratio: Decimal | None        # 합산 수익률 %
    total_trade_count: int                 # 전체 체결 주문 수
    # AI 매매 통계
    ai_pnl_amount: Decimal | None
    ai_pnl_ratio: Decimal | None
    ai_trade_count: int
    # 수동 매매 통계
    manual_pnl_amount: Decimal | None
    manual_pnl_ratio: Decimal | None
    manual_trade_count: int
    # 거래소별 breakdown
    by_exchange: list[ExchangeSummary]
    # 상위 5 코인
    top_coins: list[TopCoin] = Field(max_length=5)
    # 메타
    cached_at: datetime | None             # None = 실시간 계산


class ExchangePortfolioResponse(BaseModel):
    """GET /api/v1/portfolio/{exchange_account_id} 응답."""
    exchange_account_id: uuid.UUID
    exchange_type: str
    nickname: str | None                   # UserExchangeAccount.nickname
    total_balance_krw: Decimal | None
    krw_balance: Decimal | None            # KRW 현금 잔고 (별도 표시)
    coins: list[CoinHolding]               # KRW 제외한 코인만 (KRW는 krw_balance 필드로)
    balance_fetched_at: datetime | None    # 거래소 잔고 조회 시각
    cached_at: datetime | None
```

### 5.2 PortfolioRepository (ReadOnly)

```python
class PortfolioRepository:
    """포트폴리오 계산용 PG 조회 전용 레포지토리."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_avg_entry_prices(
        self,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID,
    ) -> dict[uuid.UUID, AvgEntryPrice]:
        """거래소 계정별 코인 가중 평균 매입가 계산.

        SQL:
            SELECT coin_id,
                   SUM(executed_quantity * executed_price)
                       / NULLIF(SUM(executed_quantity), 0) AS avg_price,
                   SUM(executed_quantity) AS total_buy_quantity
            FROM trade_orders
            WHERE user_id = :user_id
              AND exchange_account_id = :exchange_account_id
              AND order_type = 'buy'
              AND status = 'filled'
              AND executed_quantity > 0
            GROUP BY coin_id

        Returns:
            {coin_id: AvgEntryPrice(avg_price, total_buy_quantity)}

        인덱스: ix_trade_orders_user_account_status_created
        """

    async def get_trade_stats(
        self,
        user_id: uuid.UUID,
    ) -> TradeCounts:
        """전체/AI/수동 매매 통계 집계 (filled 주문 기준).

        SQL:
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE is_ai_order = true) AS ai_count,
                COUNT(*) FILTER (WHERE is_ai_order = false) AS manual_count
            FROM trade_orders
            WHERE user_id = :user_id AND status = 'filled'

        Returns:
            TradeCounts(total, ai_count, manual_count)
        """
```

**참고**: `get_avg_entry_prices()`는 **매도 수량을 고려하지 않음**. 매도 후에도 평균 매입가는 변하지 않는 것이 국내 거래소 표준 (업비트, 코인원 동일). 보유 수량은 거래소 API `get_balance()`에서 실시간 조회.

### 5.3 PortfolioService

```python
class PortfolioService:
    """포트폴리오 조회 비즈니스 로직."""

    def __init__(
        self,
        portfolio_repo: PortfolioRepository,
        exchange_account_repo: ExchangeAccountRepository,
        factory: ExchangeProviderFactory,
        market_cache: MarketCacheService,
        redis: Redis,
        settings: Settings,
    ) -> None: ...

    # -- Public API --

    async def get_portfolio_summary(
        self, user_id: uuid.UUID
    ) -> PortfolioSummaryResponse:
        """전체 자산 요약 -- 모든 거래소 합산."""

    async def get_exchange_portfolio(
        self, user_id: uuid.UUID, exchange_account_id: uuid.UUID
    ) -> ExchangePortfolioResponse:
        """거래소별 상세 포트폴리오."""

    async def invalidate_cache(
        self, user_id: uuid.UUID, exchange_account_id: uuid.UUID
    ) -> None:
        """캐시 무효화 (주문 체결 시 호출)."""

    # -- 내부 헬퍼 --

    async def _fetch_balances(
        self, account: UserExchangeAccount
    ) -> list[Balance]:
        """거래소 잔고 조회 (Redis 캐시 우선, MISS 시 API 호출).

        1. Redis GET portfolio:exchange:{user_id}:{ea_id}
        2. MISS -> Factory.create_from_account() -> provider.get_balance()
        3. Redis SET (1분 TTL)
        4. finally: provider.close()
        """

    async def _get_current_prices(
        self, exchange_type: str, symbols: list[str]
    ) -> dict[str, Decimal]:
        """심볼별 현재가 일괄 조회.

        MarketCacheService.get_ticker() 우선, fallback: Provider.get_ticker()
        심볼 -> 마켓 코드: SymbolMapper.to_market()
        """

    @staticmethod
    def _calculate_coin_pnl(
        current_price: Decimal,
        avg_entry_price: Decimal,
        quantity: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """단일 코인 PnL 계산 (순수 함수).

        Returns:
            (pnl_amount, pnl_ratio)
            pnl_amount = (current_price - avg_entry_price) * quantity
            pnl_ratio = (current_price - avg_entry_price) / avg_entry_price
            avg_entry_price == 0 -> pnl_ratio = Decimal("0")
        """
```

### 5.4 Redis 키/TTL 추가

```python
# RedisTTL 추가
PORTFOLIO_SUMMARY = 300       # 5분
PORTFOLIO_EXCHANGE = 60       # 1분
PORTFOLIO_AVG_PRICE = 600     # 10분

# RedisKey 추가
@staticmethod
def portfolio_summary(user_id: str) -> str:
    return f"portfolio:summary:{user_id}"

@staticmethod
def portfolio_exchange(user_id: str, exchange_account_id: str) -> str:
    return f"portfolio:exchange:{user_id}:{exchange_account_id}"

@staticmethod
def portfolio_avg_price(user_id: str, exchange_account_id: str) -> str:
    return f"portfolio:avg_price:{user_id}:{exchange_account_id}"
```

### 5.5 에러 팩토리

```python
class PortfolioErrors:
    """포트폴리오 관련 에러 팩토리."""

    @staticmethod
    def exchange_account_not_owned() -> AppError:
        """본인 소유가 아닌 거래소 계정 접근 시."""
        return AppError(
            code="PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED",
            message="본인 소유 거래소 계정이 아닙니다.",
            http_status=403,
        )

    @staticmethod
    def no_exchange_accounts() -> AppError:
        """등록된 거래소 계정이 없을 때."""
        return AppError(
            code="PORTFOLIO_NO_EXCHANGE_ACCOUNTS",
            message="등록된 거래소 계정이 없습니다.",
            http_status=404,
        )

    @staticmethod
    def balance_fetch_failed(exchange: str) -> AppError:
        """거래소 잔고 API 호출 실패."""
        return AppError(
            code="PORTFOLIO_BALANCE_FETCH_FAILED",
            message=f"{exchange} 잔고 조회에 실패했습니다.",
            http_status=503,
        )

    @staticmethod
    def exchange_unavailable(exchange: str) -> AppError:
        """거래소 연결 불가 (Circuit Breaker open 등)."""
        return AppError(
            code="PORTFOLIO_EXCHANGE_UNAVAILABLE",
            message=f"{exchange} 거래소에 연결할 수 없습니다.",
            http_status=503,
        )
```

### 5.6 DI 추가 (deps.py)

```python
# -- Portfolio --

def get_portfolio_repository(
    db: AsyncSession = Depends(get_db),
) -> "PortfolioRepository":
    from app.repositories.portfolio_repository import PortfolioRepository
    return PortfolioRepository(db)

def get_portfolio_service(
    portfolio_repo: "PortfolioRepository" = Depends(get_portfolio_repository),
    exchange_account_repo: "ExchangeAccountRepository" = Depends(
        get_exchange_account_repository
    ),
    factory: "ExchangeProviderFactory" = Depends(get_exchange_factory),
    market_cache: MarketCacheService = Depends(get_market_cache_service),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> "PortfolioService":
    from app.services.portfolio_service import PortfolioService
    return PortfolioService(
        portfolio_repo, exchange_account_repo, factory, market_cache, redis, settings
    )

PortfolioRepoDep = Annotated["PortfolioRepository", Depends(get_portfolio_repository)]
PortfolioServiceDep = Annotated["PortfolioService", Depends(get_portfolio_service)]
```

---

## 6. API 규격

### 6.1 GET /api/v1/portfolio

**인증**: `CurrentUser` (필수)
**쿼리 파라미터**: 없음
**캐시**: `portfolio:summary:{user_id}` TTL 300초

**응답** `ApiResponse[PortfolioSummaryResponse]` (200):
```json
{
  "data": {
    "total_balance_krw": "15234500.00",
    "total_pnl_amount": "234500.00",
    "total_pnl_ratio": "1.56",
    "total_trade_count": 42,
    "ai_pnl_amount": "180000.00",
    "ai_pnl_ratio": "2.10",
    "ai_trade_count": 28,
    "manual_pnl_amount": "54500.00",
    "manual_pnl_ratio": "0.85",
    "manual_trade_count": 14,
    "by_exchange": [
      {
        "exchange_account_id": "550e8400-e29b-41d4-a716-446655440000",
        "exchange_type": "upbit",
        "nickname": "내 업비트",
        "balance_krw": "10234500.00",
        "pnl_amount": "134500.00",
        "pnl_ratio": "1.33"
      }
    ],
    "top_coins": [
      {
        "symbol": "BTC/KRW",
        "exchange_type": "upbit",
        "quantity": "0.05000000",
        "avg_price": "85000000.00",
        "current_price": "87500000.00",
        "pnl_amount": "125000.00"
      }
    ],
    "cached_at": "2026-03-15T10:30:00Z"
  }
}
```

### 6.2 GET /api/v1/portfolio/{exchange_account_id}

**인증**: `CurrentUser` (필수)
**Path**: `exchange_account_id: uuid.UUID`
**캐시**: `portfolio:exchange:{user_id}:{exchange_account_id}` TTL 60초

**응답** `ApiResponse[ExchangePortfolioResponse]` (200):
```json
{
  "data": {
    "exchange_account_id": "550e8400-e29b-41d4-a716-446655440000",
    "exchange_type": "upbit",
    "nickname": "내 업비트",
    "total_balance_krw": "10234500.00",
    "krw_balance": "500000.00",
    "coins": [
      {
        "symbol": "BTC/KRW",
        "currency": "BTC",
        "quantity": "0.05000000",
        "available": "0.04500000",
        "locked": "0.00500000",
        "avg_entry_price": "85000000.00",
        "current_price": "87500000.00",
        "value_krw": "4375000.00",
        "pnl_amount": "125000.00",
        "pnl_ratio": "2.94",
        "weight_percent": "42.75"
      }
    ],
    "balance_fetched_at": "2026-03-15T10:29:55Z",
    "cached_at": null
  }
}
```

### 6.3 에러 응답

| 상황 | HTTP | 에러 코드 | 소스 |
|------|------|-----------|------|
| 인증 없음 | 401 | UNAUTHORIZED | AuthErrors (기존) |
| 거래소 계정 존재하지 않음 | 404 | EXCHANGE_ACCOUNT_NOT_FOUND | ExchangeErrors (기존 재사용) |
| 타 사용자 거래소 계정 | 403 | PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED | PortfolioErrors (신규) |
| 등록된 계정 없음 | 404 | PORTFOLIO_NO_EXCHANGE_ACCOUNTS | PortfolioErrors (신규) |
| 잔고 조회 실패 | 503 | PORTFOLIO_BALANCE_FETCH_FAILED | PortfolioErrors (신규) |
| 거래소 연결 불가 | 503 | PORTFOLIO_EXCHANGE_UNAVAILABLE | PortfolioErrors (신규) |

---

## 7. 모듈 의존성

```
api/v1/portfolio.py
  +-> services/portfolio_service.py
        +-> repositories/portfolio_repository.py  (PG: 평균매입가, 거래 통계)
        +-> repositories/exchange_account_repository.py  (기존)
        +-> providers/factory.py  (ExchangeProviderFactory -> get_balance())
        +-> services/market_cache_service.py  (기존 get_ticker() 재사용)
        +-> Redis (직접 주입)
              +- GET/SET portfolio:summary:{user_id}
              +- GET/SET portfolio:exchange:{user_id}:{ea_id}
              +- GET/SET portfolio:avg_price:{user_id}:{ea_id}
              +- GET ticker:{exchange}:{market}  (MarketCacheService 경유)
```

단방향 원칙 준수: `api -> service -> repository -> model`, `service -> provider(ABC)`

---

## 8. 서브태스크별 구현 가이드

### ST1: 포트폴리오 데이터 스키마 정의

**파일**: `server/app/schemas/portfolio.py`

**내용**:
- 내부 데이터 타입: `AvgEntryPrice`, `TradeCounts` (BaseModel)
- 응답 스키마: `CoinHolding`, `ExchangeSummary`, `TopCoin`, `PortfolioSummaryResponse`, `ExchangePortfolioResponse`
- 모든 금액 필드: `Decimal` 타입 (float 금지)
- `portfolio_weight`: 소수점 2자리 (0.0~100.0 범위)
- `pnl_ratio`: 소수점 2자리 퍼센트 (e.g., 2.94 = +2.94%)
- `from __future__ import annotations` 필수

**의존**: 없음

### ST2: 거래소 잔고 데이터 수집 인터페이스

**파일**: `server/app/services/portfolio_service.py` (`_fetch_balances` 메서드)

**내용**:
1. Redis 캐시 확인 (`portfolio:exchange:{user_id}:{ea_id}` 중 잔고 부분)
2. MISS → `ExchangeProviderFactory.create_from_account(account, enc_key)` → `provider.get_balance()`
3. 결과를 JSON 직렬화하여 Redis에 SET (1분 TTL)
4. Provider 오류 → 부분 실패 허용 (포트폴리오 요약에서는 해당 거래소 제외)
5. `finally`에서 `provider.close()` 보장
6. KRW 잔고 분리: `currency == "KRW"` → CoinHolding에 symbol="KRW"로 포함

**주의사항**:
- Provider 생성에 `settings.EXCHANGE_API_KEY_SECRET` 필요 (ExchangeAccountService 패턴 참조)
- Circuit Breaker 상태 확인 후 호출 (Factory 내부 처리)
- Balance의 `available + locked = total` 속성 활용
- Redis graceful degradation: `except Exception` 후 fallback (`coin_service` 패턴)

**의존**: ST1

### ST3: 평균 매입가 계산 서비스

**파일**: `server/app/repositories/portfolio_repository.py`

**내용**:
1. `get_avg_entry_prices()` — SQLAlchemy 집계:
   ```python
   stmt = (
       select(
           TradeOrder.coin_id,
           (func.sum(TradeOrder.executed_quantity * TradeOrder.executed_price)
            / func.nullif(func.sum(TradeOrder.executed_quantity), 0)).label("avg_price"),
           func.sum(TradeOrder.executed_quantity).label("total_buy_quantity"),
       )
       .where(
           TradeOrder.user_id == user_id,
           TradeOrder.exchange_account_id == exchange_account_id,
           TradeOrder.order_type == "buy",
           TradeOrder.status == "filled",
           TradeOrder.executed_quantity > 0,
       )
       .group_by(TradeOrder.coin_id)
   )
   ```
2. `func.nullif` — 0 나누기 방지
3. 결과를 `dict[UUID, AvgEntryPrice]`로 반환
4. 캐시 계층: 서비스에서 Redis 캐시 관리 (10분 TTL)

**활용 인덱스**: `ix_trade_orders_user_account_status_created` (user_id, exchange_account_id, status, created_at)

**의존**: ST1

### ST4: 수익/손실(PnL) 계산 엔진

**파일**: `server/app/services/portfolio_service.py` (`_calculate_coin_pnl` 정적 메서드)

**내용**:
1. **미실현 PnL** (보유 중 코인):
   ```python
   pnl_amount = (current_price - avg_entry_price) * quantity
   pnl_ratio = (current_price - avg_entry_price) / avg_entry_price  # Decimal
   ```
2. **AI/수동 분리**: `PortfolioRepository.get_trade_stats()` — `COUNT FILTER` 사용
3. **총 PnL**: 모든 거래소의 미실현 PnL 합산

**엣지 케이스**:
- `avg_entry_price == 0`: `pnl_ratio = Decimal("0")` (방어)
- `current_price is None` (ticker 캐시 없음): `pnl_amount = None`, `pnl_ratio = None`
- `avg_entry_price is None` (외부 입금, 매수 이력 없음): `pnl_amount = None`, `pnl_ratio = None`
- 음수 잔고: 불가능 (거래소 제약), 무시

**의존**: ST3

### ST5: 원화 환산 및 가격 정규화

**파일**: `server/app/services/portfolio_service.py` (`_get_current_prices` 메서드)

**내용**:
1. 현재 KRW 기축 거래소만 지원 → 별도 환율 변환 불필요
2. `MarketCacheService.get_ticker(exchange, market)` → `price` 필드 (KRW)
3. 캐시 MISS 시 `Provider.get_ticker(market)` fallback (optional, 성능 트레이드오프)
4. 심볼 → 마켓 코드 변환: `SymbolMapper.to_market(exchange_type, f"{currency}/KRW")`
5. KRW 자체는 current_price = Decimal("1") 고정

**향후 확장 포인트** (v2):
- `CurrencyConverter` 인터페이스 → `KrwDirectConverter`, `UsdtToKrwConverter`
- USDT/KRW 환율: 외부 API 또는 거래소 간 차익 평균

**의존**: ST2

### ST6: 포트폴리오 조회 비즈니스 로직

**파일**: `server/app/services/portfolio_service.py`

**내용**:
1. `get_portfolio_summary()`:
   - 모든 거래소 계정 조회 → `asyncio.gather`로 병렬 잔고 수집
   - 거래소별 PnL 계산 → 합산
   - top_coins: 보유 가치(value_krw) 기준 내림차순 상위 5개
   - AI/수동 거래 통계: `get_trade_stats()` 호출
   - **부분 실패 허용**: 특정 거래소 조회 실패 시 해당 거래소 제외, 나머지 반환

2. `get_exchange_portfolio()`:
   - 소유권 검증: account 존재 여부 → `ExchangeErrors.account_not_found()` (404, 기존 재사용)
   - 소유권 검증: `account.user_id != user_id` → `PortfolioErrors.exchange_account_not_owned()` (403)
   - 잔고 + 시세 + 평균 매입가 조합
   - 각 코인의 `weight_percent` 계산
   - KRW 잔고는 `krw_balance` 별도 필드, coins 배열에는 KRW 제외

**부분 실패 처리**:
```python
results = await asyncio.gather(
    *[self._fetch_exchange_data(account) for account in accounts],
    return_exceptions=True,
)
# isinstance(result, Exception) -> 해당 거래소 제외, 로그만 기록
```

**의존**: ST3, ST4, ST5

### ST7: Redis 캐싱 전략 구현

**파일**: `server/app/services/portfolio_service.py`, `server/app/core/redis_keys.py`

**내용**:
1. Redis 키/TTL 상수 추가 (§5.4 참조)
2. 캐시 GET/SET 패턴 (graceful degradation):
   ```python
   async def _get_cached(self, key: str) -> dict | None:
       try:
           raw = await self._redis.get(key)
           return json.loads(raw) if raw else None
       except Exception:
           return None

   async def _set_cache(self, key: str, data: dict, ttl: int) -> None:
       try:
           await self._redis.set(key, json.dumps(data, default=str), ex=ttl)
       except Exception:
           logger.warning("Cache write failed: %s", key)
   ```
3. `invalidate_cache()` — 주문 체결 시 관련 키 DEL (3개)
4. 무효화 트리거: OrderService에서 상태 전이(→filled) 시 호출
   - v1: OrderService에서 직접 Redis DEL (간단한 접근)
   - v2: 이벤트 기반 무효화 (Redis Pub/Sub)

**의존**: ST6

### ST8: 포트폴리오 API 엔드포인트 구현

**파일**: `server/app/api/v1/portfolio.py`

**내용**:
```python
router = APIRouter(prefix="/portfolio", tags=["portfolio"])

@router.get("", response_model=ApiResponse[PortfolioSummaryResponse])
async def get_portfolio_summary(
    current_user: CurrentUser,
    service: PortfolioServiceDep,
) -> ApiResponse[PortfolioSummaryResponse]:
    data = await service.get_portfolio_summary(current_user.id)
    return ApiResponse(data=data)

@router.get(
    "/{exchange_account_id}",
    response_model=ApiResponse[ExchangePortfolioResponse],
)
async def get_exchange_portfolio(
    exchange_account_id: UUID,
    current_user: CurrentUser,
    service: PortfolioServiceDep,
) -> ApiResponse[ExchangePortfolioResponse]:
    data = await service.get_exchange_portfolio(
        current_user.id, exchange_account_id
    )
    return ApiResponse(data=data)
```

**라우터 등록** (`api/v1/__init__.py` 수정, main.py 변경 불필요):
```python
# api/v1/__init__.py 에 추가:
from app.api.v1.portfolio import router as portfolio_router
router.include_router(portfolio_router)
```

**의존**: ST6, ST7

### ST9: 포트폴리오 API 통합 테스트

**파일**: `server/tests/integration/test_portfolio_api.py`

**테스트 케이스** (~9건):

| # | 테스트 | 설명 |
|---|--------|------|
| T1 | 전체 포트폴리오 요약 정상 조회 | MockProvider + Redis ticker 설정 |
| T2 | 거래소별 상세 정상 조회 | 코인별 데이터 + portfolio_weight 검증 |
| T3 | 인증 실패 | 토큰 없이 → 401 |
| T4 | 타 사용자 계정 접근 | → 403 PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED |
| T5 | 거래소 계정 없음 | → 빈 포트폴리오 (총액 0, by_exchange=[]) |
| T6 | 거래소 API 실패 → 부분 응답 | 1개 성공 + 1개 실패 → 성공 데이터만 |
| T7 | 매수 이력 없는 코인 | avg_entry_price=null, pnl=null |
| T8 | 캐시 HIT 검증 | Redis에 미리 저장 → Provider 미호출 확인 |
| T9 | 캐시 무효화 후 재조회 | DEL 후 Provider 재호출 확인 |

**Mock 전략**:
- `ExchangeProviderFactory.create_from_account()` → MockProvider
- MockProvider.get_balance() → 고정 Balance 반환
- MarketCacheService → Redis에 미리 ticker 세팅

**의존**: ST8

### ST10: 도넛 차트 데이터 포맷 및 문서화

**내용**:
- 응답의 `coins[].weight_percent` 필드가 도넛 차트 데이터 소스
- KRW 현금은 `krw_balance` 별도 필드로 제공 (도넛 차트에서는 클라이언트에서 별도 슬라이스로 추가)
- 클라이언트에서 상위 N개 + "기타" 그룹핑
- `weight_percent`의 합 = 100.00 (반올림 오차 보정: remainder adjustment)
- `total_balance_krw == 0` 또는 `current_price` 없는 코인 → `weight_percent = None`

**Flutter 소비 패턴** (참고):
```dart
final chartData = coins
    .where((c) => c.weightPercent != null)
    .map((c) => DonutSlice(
        label: c.symbol,
        value: c.weightPercent!.toDouble(),
    ))
    .toList();
// KRW 현금 슬라이스는 krwBalance에서 별도 추가
```

**의존**: ST8

---

## 9. 코드 컨벤션 체크리스트

1. 모든 I/O 함수는 `async`/`await`
2. `Decimal` 사용 (float 금지) — 금액/수량/비율 모두
3. `from __future__ import annotations` 파일 상단 필수
4. `ApiResponse[T]` 래퍼로 응답 반환
5. Google 스타일 docstring
6. mypy `--strict` 호환: 구체 타입 사용 (dict[str, Any] 지양)
7. Redis graceful degradation: `except Exception` 후 None/fallback
8. Provider 생성/해제: `try/finally` 패턴 (provider.close() 보장)
9. 에러 코드 네임스페이스: `PORTFOLIO_` 접두사

---

## 10. 테스트 전략

### 단위 테스트 (~25건)

| 영역 | 테스트 | 건수 |
|------|--------|------|
| PortfolioRepository | avg_entry_price 쿼리, 0 나누기 방어, 다중 코인, trade_stats | 6 |
| _calculate_coin_pnl | 정상, 손실, 0가격, None 방어 | 4 |
| get_portfolio_summary | 단일/다중 거래소, 빈 잔고, 부분 실패, top_coins 정렬 | 6 |
| get_exchange_portfolio | 정상, 소유권 실패, 잔고 없음, KRW 포함 | 4 |
| 캐시 | HIT/MISS, 무효화, graceful degradation | 3 |
| 스키마 | 응답 직렬화, portfolio_weight 합계 보정 | 2 |

### 통합 테스트 (~9건)

위 §8 ST9 참조.

---

## 11. 성능 기준

| 항목 | 목표 | 비고 |
|------|------|------|
| 포트폴리오 요약 (캐시 HIT) | < 50ms | Redis GET + JSON parse |
| 포트폴리오 요약 (캐시 MISS, 1거래소) | < 2s | Provider API 호출 포함 |
| 포트폴리오 요약 (캐시 MISS, 2거래소) | < 3s | asyncio.gather 병렬 |
| 거래소별 상세 (캐시 HIT) | < 50ms | Redis GET |
| 거래소별 상세 (캐시 MISS) | < 2s | Provider + SQL 집계 |
| 평균 매입가 SQL 쿼리 | < 100ms | 인덱스 활용 |

---

## 12. 향후 확장 (v2 범위)

- WS 기반 실시간 포트폴리오 업데이트 (Pub/Sub)
- FIFO 방식 평균 매입가 (옵션)
- USDT/USD → KRW 환율 변환 (해외 거래소)
- 포트폴리오 히스토리 (일별 스냅샷)
- 도넛 차트 커스텀 그룹핑 (API)
- Celery 주기적 포트폴리오 스냅샷 저장 (통계/리포트용)
- MarketCacheService.get_tickers_bulk() 일괄 조회 최적화

---

## 13. 현재 상태

**상태**: 구현 완료 (2026-03-15)

### 구현 결과
- 신규 파일 4개, 수정 파일 4개, 테스트 파일 3개
- 단위 테스트: 24/24 통과 (서비스 18건, 리포지토리 6건)
- 통합 테스트: 21/21 통과
- 기존 테스트 스위트: 505+ 전체 통과
- 코드 리뷰: PASS (CRITICAL 0, WARNING 0)

### 리뷰 중 수정사항
- W1: `cached_at` 의미 분리 (실시간=null, 캐시=write_timestamp)
- W2: avg_entry_price 매핑 — Coin JOIN + split_part currency 키 변환 구현
- ST10: weight_percent remainder adjustment 계산 오류 수정 (code-architect)
