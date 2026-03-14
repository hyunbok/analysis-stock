# v1-14 주문 실행 및 거래 API — 설계서

> **작성**: project-architect (시스템 아키텍처/흐름/구현계획), code-architect (코드 구조/스키마/상태 머신), db-architect (쿼리/인덱스/수수료 테이블)
> **대상 태스크**: v1-14 — 시장가/지정가 주문, 주문 취소, 미체결 일괄 취소, 거래소별 실시간 동기화
> **현재 상태**: 구현 완료 (2026-03-14)

---

## 1. 개요

거래소 주문 생성(시장가/지정가), 조회, 취소, 일괄 취소 API를 구현한다. 기존 `TradeOrder` 모델(`models/trading.py`)과 거래소 Provider(`providers/`)의 `place_order()`, `cancel_order()` 메서드를 활용하며, 주문 상태 머신으로 상태 전이를 관리한다.

**의존성**: v1-11 (거래소 계정 관리), v1-12 (WebSocket 시세 허브), v1-13 (코인 마스터)

**핵심 요구사항**:
- 시장가/지정가 주문 생성 (BUY/SELL)
- 주문 상태 머신: PENDING → OPEN → FILLED/PARTIAL/CANCELLED/FAILED
- 주문 내역 조회 (필터 + 페이지네이션)
- 단건/일괄 주문 취소 (부분 성공 허용)
- 수수료 계산 및 응답 포함
- 거래소 에러 → AppError 매핑
- Circuit Breaker 통합 (기존 BaseExchangeProvider 재사용)

---

## 2. 전체 아키텍처

### 2.1 주문 생성 데이터 흐름

```
Flutter App ──POST /api/v1/orders──▶ FastAPI Server
                                          │
                                    ┌─────▼──────┐
                                    │ Validation  │ 스키마 검증 + model_validator
                                    └─────┬──────┘
                                          │
                                    ┌─────▼──────┐
                                    │ OrderService│
                                    │  1. 계정 소유권 확인
                                    │  2. 코인 조회 → market_code
                                    │  3. TradeOrder INSERT (PENDING)
                                    │  4. Provider 생성 (복호화)
                                    │  5. provider.place_order()
                                    │  6. 상태 전이 (OPEN/FILLED/FAILED)
                                    │  7. 수수료/체결 정보 업데이트
                                    └─────┬──────┘
                                          │
                                    ┌─────▼──────┐
                                    │ Exchange    │ Upbit/CoinOne Provider
                                    │ Provider    │ (_execute_rest → Rate Limiter → CB)
                                    └─────┬──────┘
                                          │
                                    ┌─────▼──────┐
                                    │ DB Update   │ status, exchange_order_id,
                                    │             │ executed_quantity, fee, executed_price
                                    └─────────────┘
```

### 2.2 주문 취소 데이터 흐름

```
Flutter App ──DELETE /api/v1/orders/{id}──▶ FastAPI Server
                                                 │
                                           ┌─────▼──────┐
                                           │ OrderService│
                                           │  1. 주문 조회 + 소유권
                                           │  2. 취소 가능 상태 확인
                                           │  3. provider.cancel_order()
                                           │  4. 상태 전이 → CANCELLED
                                           │  5. 부분 체결 수량 보존
                                           └─────────────┘
```

### 2.3 일괄 취소 데이터 흐름

```
Flutter App ──POST /api/v1/orders/batch-cancel──▶ FastAPI Server
                                                       │
                                                 ┌─────▼──────┐
                                                 │ OrderService│
                                                 │  1. order_ids 소유권 확인
                                                 │  2. 취소 가능 주문 필터
                                                 │  3. asyncio.gather(cancel_each)
                                                 │  4. 결과 취합 (성공/실패)
                                                 └─────────────┘
```

---

## 3. 주문 상태 머신

### 3.1 상태 정의

| 상태 | 설명 |
|------|------|
| `pending` | DB에 생성됨, 거래소 미전송 (또는 전송 중) |
| `open` | 거래소에서 수신 완료, 체결 대기 (지정가) |
| `filled` | 완전 체결 |
| `partial` | 부분 체결 (잔량 대기 중) |
| `cancelled` | 사용자 취소 (부분 체결 수량/수수료 보존) |
| `failed` | 거래소 거부 또는 호출 실패 |

### 3.2 상태 전이 다이어그램

```
                    ┌──────────────┐
                    │   PENDING    │  (DB INSERT, 거래소 전송 전)
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │   OPEN   │ │  FILLED  │ │  FAILED  │
        │(지정가   │ │(시장가   │ │(거래소   │
        │ 대기중)  │ │ 즉시체결)│ │ 거부)    │
        └────┬─────┘ └──────────┘ └──────────┘
             │
      ┌──────┼──────┐
      ▼      ▼      ▼
┌────────┐┌──────┐┌──────────┐
│PARTIAL ││FILLED││CANCELLED │
│(부분   ││(완전 ││(사용자   │
│ 체결)  ││ 체결)││ 취소)    │
└───┬────┘└──────┘└──────────┘
    │
    ├──────┐
    ▼      ▼
┌──────┐┌──────────┐
│FILLED││CANCELLED │
│(잔량 ││(부분취소 │
│ 체결) ││잔량취소) │
└──────┘└──────────┘
```

### 3.3 상태 전이 코드

```python
# services/order_service.py 내 모듈 레벨 클래스

class OrderStateMachine:
    """주문 상태 전이 규칙 관리."""

    _TRANSITIONS: dict[str, set[str]] = {
        "pending": {"open", "filled", "failed"},
        "open": {"filled", "partial", "cancelled"},
        "partial": {"filled", "cancelled"},
    }

    _CANCELLABLE: set[str] = {"pending", "open", "partial"}

    @classmethod
    def validate_transition(cls, current: str, target: str) -> None:
        """상태 전이 가능 여부 검증.

        Raises:
            AppError(INVALID_ORDER_TRANSITION): 허용되지 않는 전이
        """
        allowed = cls._TRANSITIONS.get(current, set())
        if target not in allowed:
            raise OrderErrors.invalid_status_transition(current, target)

    @classmethod
    def can_cancel(cls, status: str) -> bool:
        """취소 가능 상태인지 확인."""
        return status in cls._CANCELLABLE
```

> **설계 결정**: 별도 `trading/state_machine.py` 대신 `order_service.py` 모듈 내 클래스로 배치.
> 이유: 상태 머신이 OrderService에서만 사용되고 코드가 작으므로 별도 모듈 불필요.

### 3.4 DB CHECK 제약 변경 (Migration)

기존: `status IN ('pending', 'filled', 'cancelled', 'partial')`
변경: `status IN ('pending', 'open', 'filled', 'cancelled', 'partial', 'failed')`

providers/enums.py `OrderStatus`에도 `OPEN = "open"`, `FAILED = "failed"` 추가.

---

## 4. API 엔드포인트 상세

### 4.1 주문 생성 — `POST /api/v1/orders`

| 항목 | 값 |
|------|-----|
| 인증 | 필수 (CurrentUser) |
| 태그 | orders |
| 응답 | 201 Created |

**요청 스키마**:
```python
class CreateOrderRequest(BaseModel):
    exchange_account_id: UUID
    coin_id: UUID
    side: OrderSide           # buy / sell (providers/enums.py 재사용)
    method: OrderMethod       # market / limit
    quantity: Decimal | None = None   # 코인 수량 (LIMIT 필수, MARKET SELL 필수)
    amount: Decimal | None = None     # KRW 총액 (MARKET BUY 시 사용)
    price: Decimal | None = None      # 지정가 (LIMIT 필수)

    @model_validator(mode="after")
    def validate_order_params(self) -> Self:
        if self.method == OrderMethod.LIMIT:
            if self.price is None:
                raise ValueError("price required for LIMIT order")
            if self.quantity is None:
                raise ValueError("quantity required for LIMIT order")
            if self.price <= 0 or self.quantity <= 0:
                raise ValueError("price and quantity must be positive")
        elif self.method == OrderMethod.MARKET:
            if self.side == OrderSide.BUY:
                if self.amount is None:
                    raise ValueError("amount (KRW) required for MARKET BUY")
                if self.amount <= 0:
                    raise ValueError("amount must be positive")
            else:  # SELL
                if self.quantity is None:
                    raise ValueError("quantity required for MARKET SELL")
                if self.quantity <= 0:
                    raise ValueError("quantity must be positive")
        return self
```

**응답 스키마** — `ApiResponse[OrderResponse]` (201):
```python
class OrderResponse(BaseModel):
    id: UUID
    exchange_account_id: UUID
    coin_id: UUID
    coin_symbol: str                   # JOIN Coin.symbol
    exchange_type: ExchangeType         # Coin.exchange_type (Enum)
    side: OrderSide                    # buy / sell (Enum)
    method: OrderMethod                # market / limit (Enum)
    status: OrderStatus                # pending/open/filled/partial/cancelled/failed (Enum)
    price: Decimal | None              # 지정가 또는 시장가 매수 KRW 총액
    quantity: Decimal | None           # 주문 수량
    amount: Decimal | None             # 주문 금액 (시장가 매수 KRW)
    executed_quantity: Decimal          # 체결 수량
    executed_price: Decimal | None     # 평균 체결가
    fee: Decimal                       # 수수료 금액
    fee_rate: Decimal | None           # 적용 수수료율
    fee_currency: str | None           # 수수료 통화 (KRW, BTC 등)
    exchange_order_id: str | None      # 거래소 측 주문 ID
    is_ai_order: bool
    created_at: datetime
    updated_at: datetime
    executed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
```

**로직**:
1. `exchange_account_id` → 소유권 확인 (`user_id` 일치) → 없으면 `ExchangeErrors.account_not_found()`
2. `coin_id` → Coin 조회 → 없으면 `CoinErrors.not_found()`
3. Coin의 `exchange_type` + `market_code`로 거래소 마켓 코드 확보
4. TradeOrder INSERT (`status = "pending"`)
5. Provider 생성: `factory.create_from_account(account, encryption_key)`
6. `provider.place_order(Order(...))` 호출
7. 성공 시: `OrderResult` → DB 업데이트 (status, exchange_order_id, executed_quantity, fee, executed_price)
8. 실패 시: `status = "failed"`, 에러 로그
9. AuditService 로깅

### 4.2 주문 목록 — `GET /api/v1/orders`

| 항목 | 값 |
|------|-----|
| 인증 | 필수 (CurrentUser) |
| 태그 | orders |

**쿼리 파라미터**:
| 파라미터 | 타입 | 필수 | 제약 | 설명 |
|----------|------|------|------|------|
| exchange_account_id | UUID | N | - | 거래소 계정 필터 |
| coin_id | UUID | N | - | 코인 필터 |
| status | OrderStatus | N | Enum (pending/open/filled/partial/cancelled/failed) | 상태 필터 |
| side | OrderSide | N | Enum (buy/sell) | 방향 필터 |
| from_dt | datetime | N | ISO 8601 | 시작일 |
| to_dt | datetime | N | ISO 8601 | 종료일 |
| page | int | N | ge=1 | 페이지 (기본 1) |
| size | int | N | ge=1, le=100 | 페이지 크기 (기본 20) |

**응답 스키마** — `ApiResponse[PaginatedOrders]`:
```python
class PaginatedOrders(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    size: int
    pages: int   # ceil(total / size)
```

### 4.3 주문 상세 — `GET /api/v1/orders/{order_id}`

| 항목 | 값 |
|------|-----|
| 인증 | 필수 (CurrentUser) |
| 태그 | orders |

**로직**:
1. `order_id`로 조회 → 없으면 `OrderErrors.not_found()`
2. `user_id` 소유권 확인 → 불일치 시 `OrderErrors.not_found()` (403 대신 404로 정보 노출 방지)
3. Coin JOIN으로 `coin_symbol`, `exchange_type` 포함 응답

### 4.4 주문 취소 — `DELETE /api/v1/orders/{order_id}`

| 항목 | 값 |
|------|-----|
| 인증 | 필수 (CurrentUser) |
| 태그 | orders |

**응답** — `ApiResponse[OrderResponse]`

**로직**:
1. 주문 조회 + 소유권 확인
2. `OrderStateMachine.can_cancel(status)` → False면 `OrderErrors.cannot_cancel(status)`
3. Provider 생성 → `provider.cancel_order(market, exchange_order_id)` 호출
4. 성공 시: 상태 → `cancelled` (부분 체결 수량/수수료 보존)
5. 실패 시 (이미 체결): 상태 동기화 → `filled`
6. AuditService 로깅

### 4.5 일괄 취소 — `POST /api/v1/orders/batch-cancel`

| 항목 | 값 |
|------|-----|
| 인증 | 필수 (CurrentUser) |
| 태그 | orders |

> **라우터 등록 순서**: `POST /batch-cancel`을 `GET /{order_id}`보다 먼저 등록 — path 캡처 방지

**요청 스키마**:
```python
class BatchCancelRequest(BaseModel):
    order_ids: list[UUID] = Field(..., min_length=1, max_length=20)
```

**응답 스키마** — `ApiResponse[BatchCancelResponse]`:
```python
class BatchCancelFailure(BaseModel):
    order_id: UUID
    reason: str

class BatchCancelResponse(BaseModel):
    success_count: int
    failed_count: int
    success_ids: list[UUID]
    failed: list[BatchCancelFailure]
```

**로직**:
1. 모든 `order_ids` 소유권 일괄 확인
2. 취소 가능 상태 필터링
3. `asyncio.gather(*[cancel_single(oid) for oid in cancellable_ids], return_exceptions=True)` 병렬 처리
4. 결과 취합: 성공/실패 분류
5. 부분 성공 허용 — HTTP 200으로 응답 (개별 실패는 `failed` 배열에 포함)

---

## 5. 에러 정의

`core/exceptions.py`에 `OrderErrors` 클래스 추가:

```python
class OrderErrors:
    """주문 도메인 에러 팩토리."""

    @staticmethod
    def not_found() -> AppError:
        return AppError("ORDER_NOT_FOUND", "주문을 찾을 수 없습니다.", 404)

    @staticmethod
    def invalid_status_transition(current: str, target: str) -> AppError:
        return AppError(
            "INVALID_ORDER_TRANSITION",
            f"주문 상태 전이 불가: {current} → {target}",
            409,
        )

    @staticmethod
    def cannot_cancel(status: str) -> AppError:
        return AppError(
            "ORDER_CANNOT_CANCEL",
            f"취소할 수 없는 상태입니다: {status}",
            422,
        )

    @staticmethod
    def insufficient_balance() -> AppError:
        return AppError("INSUFFICIENT_BALANCE", "잔고가 부족합니다.", 422)

    @staticmethod
    def exchange_order_failed(detail: str) -> AppError:
        return AppError("EXCHANGE_ORDER_FAILED", f"주문 처리 실패: {detail}", 502)

    @staticmethod
    def exchange_unavailable() -> AppError:
        return AppError(
            "EXCHANGE_UNAVAILABLE",
            "거래소에 일시적으로 연결할 수 없습니다. 잠시 후 재시도해주세요.",
            503,
        )
```

---

## 6. 예외 처리 전략

### 6.1 Provider 예외 → AppError 매핑

```python
# order_service.py 내부 헬퍼
@staticmethod
def _map_exchange_error(exc: ExchangeError) -> AppError:
    """거래소 Provider 예외 → HTTP 응답용 AppError 변환."""
    match exc:
        case ExchangeInsufficientBalanceError():
            return OrderErrors.insufficient_balance()
        case ExchangeUnavailableError():
            return OrderErrors.exchange_unavailable()
        case ExchangeRateLimitError() as e:
            return ExchangeErrors.rate_limited(e.exchange, e.retry_after_seconds)
        case ExchangeAuthError() as e:
            return ExchangeErrors.auth_failed(e.exchange)
        case ExchangePermissionError() as e:
            return ExchangeErrors.permission_denied(e.exchange, "TRADE")
        case ExchangeOrderError() as e:
            return OrderErrors.exchange_order_failed(str(e))
        case _:
            return OrderErrors.exchange_order_failed("알 수 없는 거래소 오류")
```

> **설계 결정**: 매핑 로직을 OrderService 내부 헬퍼로 배치.
> 이유: 별도 adapter 모듈은 과도한 추상화. ExchangeAccountService._verify_with_provider()와 동일 패턴 유지.

### 6.2 재시도 전략

| 작업 | 재시도 | 이유 |
|------|--------|------|
| 주문 생성 (시장가) | **없음** | 이중 주문 위험 |
| 주문 생성 (지정가) | **없음** | 이중 주문 위험 (네트워크 타임아웃 시 거래소 접수 여부 확인 불가) |
| 주문 취소 | 3회 지수 백오프 | 멱등 연산 |
| 상태 동기화 | 3회 지수 백오프 | 멱등 연산 |

> **주문 생성 재시도 금지** (시장가/지정가 모두): 네트워크 오류 시 거래소에서 이미 접수했을 가능성. DB에 FAILED로 저장하고 클라이언트에 502 반환. 재시도는 클라이언트 책임.

### 6.3 Circuit Breaker 동작

기존 `BaseExchangeProvider._execute_rest()`에 이미 통합:
- Rate Limiter → Circuit Breaker → 실제 HTTP 호출 순서
- CB OPEN 시 `ExchangeUnavailableError` 즉시 발생
- OrderService에서 별도 CB 로직 추가 불필요

### 6.4 부분 체결 처리

```python
# 주문 취소 후 거래소에서 executed_quantity > 0 이면:
# 상태: PARTIAL → CANCELLED (상태 머신 허용)
# executed_quantity, fee: 보존 (실제 체결된 수량/수수료)
# executed_price: 보존 (평균 체결가)
```

---

## 7. 수수료 계산 로직

### 7.1 수수료 조회 흐름

```
주문 생성 시:
  1. Provider.get_trading_fee(market) 호출 → TradingFee(maker_rate, taker_rate)
  2. 실패 시: trading_fees DB 테이블 → Redis 캐시 fallback
  3. method == MARKET → taker_fee 적용
     method == LIMIT  → maker_fee 적용
  4. fee = executed_amount × fee_rate
```

### 7.2 OrderService 내부 수수료 계산

```python
async def _calculate_fee(
    self,
    provider: ExchangeProvider,
    market: str,
    method: str,
) -> Decimal:
    """수수료율 조회. Provider → DB fallback."""
    try:
        trading_fee = await provider.get_trading_fee(market)
        rate = trading_fee.taker_fee if method == "market" else trading_fee.maker_fee
    except ExchangeError:
        # fallback: trading_fees 테이블 조회
        rate = await self._get_fallback_fee_rate(
            provider.exchange_type.value, method
        )
    return rate

async def _get_fallback_fee_rate(
    self, exchange_type: str, method: str,
) -> Decimal:
    """trading_fees 테이블에서 기본(tier=0) 수수료율 조회."""
    fee = await self._order_repo.get_trading_fee(exchange_type, tier=0)
    if fee is None:
        return Decimal("0.0005")  # 최종 fallback: 0.05%
    return fee.taker_rate if method == "market" else fee.maker_rate
```

> **설계 결정**: OrderService 내 private 메서드로 수수료 조회.
> 이유: FeeCalculator 별도 클래스는 과도한 분리. 수수료 로직이 확장되면 그때 분리.
> **fee_rate 저장 권장**: db-architect 의견 수정 반영 — 수수료 이상 탐지(`fee / executed_amount` vs `fee_rate` 비교), 감사 이력 보존, 티어 변경 시 소급 계산 불필요.

---

## 8. 파일 구조

### 8.1 신규 생성 파일

| 파일 | 설명 |
|------|------|
| `server/app/schemas/order.py` | 주문 요청/응답 스키마, 페이지네이션, BatchCancel |
| `server/app/repositories/order_repository.py` | TradeOrder DB CRUD + TradingFee 조회 |
| `server/app/services/order_service.py` | OrderService + OrderStateMachine |
| `server/app/api/v1/orders.py` | 주문 API 엔드포인트 (5개) |
| `server/app/models/trading_fee.py` | TradingFee DB 모델 |
| `server/app/models/trade_order_event.py` | TradeOrderEvent DB 모델 |
| `server/alembic/versions/006_v1_14_order_trading.py` | Migration: CHECK 변경 + 인덱스 + trading_fees + trade_order_events 테이블 |
| `server/tests/unit/test_order_service.py` | OrderService 단위 테스트 |
| `server/tests/unit/test_order_repository.py` | OrderRepository 단위 테스트 |
| `server/tests/unit/test_order_state_machine.py` | OrderStateMachine 단위 테스트 |
| `server/tests/integration/test_orders_api.py` | 주문 API 통합 테스트 |

### 8.2 수정 파일

| 파일 | 변경 내용 |
|------|----------|
| `server/app/api/v1/__init__.py` | orders 라우터 등록 (기존 주석 해제 + import) |
| `server/app/core/deps.py` | OrderRepository, OrderService DI 팩토리 + 타입 별칭 |
| `server/app/core/exceptions.py` | OrderErrors 클래스 추가 |
| `server/app/providers/enums.py` | OrderStatus에 `OPEN`, `FAILED` 추가 |
| `server/app/models/trading.py` | TradeOrder CHECK 제약 변경, 컬럼 추가 (`amount`, `executed_price`, `fee_rate`, `fee_currency`), events relationship 추가 |

---

## 9. DI (의존성 주입) 설계

### 9.1 DI 팩토리 함수 (`core/deps.py` 추가)

```python
# ── Order ─────────────────────────────────────────────────────────────────────

def get_order_repository(db: AsyncSession = Depends(get_db)) -> "OrderRepository":
    from app.repositories.order_repository import OrderRepository

    return OrderRepository(db)


def get_order_service(
    order_repo: "OrderRepository" = Depends(get_order_repository),
    exchange_account_repo: "ExchangeAccountRepository" = Depends(
        get_exchange_account_repository
    ),
    factory: "ExchangeProviderFactory" = Depends(get_exchange_factory),
    settings: Settings = Depends(get_settings),
) -> "OrderService":
    from app.services.order_service import OrderService

    return OrderService(order_repo, exchange_account_repo, factory, settings)


OrderRepoDep = Annotated["OrderRepository", Depends(get_order_repository)]
OrderServiceDep = Annotated["OrderService", Depends(get_order_service)]
```

### 9.2 라우터 등록 (`api/v1/__init__.py`)

```python
from app.api.v1.orders import router as orders_router

router.include_router(orders_router, prefix="/orders", tags=["orders"])
```

---

## 10. 서비스 계층 상세

### 10.1 OrderService

```python
class OrderService:
    """주문 생성/조회/취소 비즈니스 로직."""

    def __init__(
        self,
        order_repo: OrderRepository,
        exchange_account_repo: ExchangeAccountRepository,
        factory: ExchangeProviderFactory,
        settings: Settings,
    ) -> None:
        self._order_repo = order_repo
        self._exchange_account_repo = exchange_account_repo
        self._factory = factory
        self._settings = settings

    # ── 주문 생성 ──────────────────────────────────────────────────────

    async def create_order(
        self, user_id: UUID, request: CreateOrderRequest,
    ) -> OrderResponse:
        """주문 생성 → 거래소 전송 → DB 업데이트.

        1. 계정 소유권 + 코인 존재 확인
        2. TradeOrder INSERT (status=PENDING)
        3. Provider 생성 + place_order() 호출
        4. 결과에 따라 상태 전이 + DB 업데이트
        5. 실패 시 status=FAILED + 에러 raise
        """
        # 1. 계정 조회 + 소유권 확인
        account = await self._exchange_account_repo.get_by_id(
            request.exchange_account_id
        )
        if account is None or account.user_id != user_id:
            raise ExchangeErrors.account_not_found()

        # 2. 코인 조회 → market_code 확보
        coin = await self._order_repo.get_coin(request.coin_id)
        if coin is None:
            raise CoinErrors.not_found()

        # 3. DB INSERT (PENDING)
        order = await self._order_repo.create(
            user_id=user_id,
            exchange_account_id=request.exchange_account_id,
            coin_id=request.coin_id,
            order_type=request.side.value,
            order_method=request.method.value,
            price=request.price,
            quantity=request.quantity,
            amount=request.amount,
            status="pending",
        )

        # 4. Provider 생성 + 주문 실행
        provider = None
        try:
            enc_key = bytes.fromhex(self._settings.EXCHANGE_API_KEY_SECRET)
            provider = await self._factory.create_from_account(account, enc_key)

            # Provider Order 모델 변환
            provider_order = self._build_provider_order(
                coin.market_code, request
            )
            result = await provider.place_order(provider_order)

            # 5. 성공: 상태 전이 + DB 업데이트
            new_status = self._determine_status(result)
            OrderStateMachine.validate_transition("pending", new_status)

            # 수수료율 조회
            fee_rate = await self._get_fee_rate(provider, coin.market_code, request.method.value)

            await self._order_repo.update_after_execution(
                order_id=order.id,
                status=new_status,
                exchange_order_id=result.exchange_order_id,
                executed_quantity=result.executed_quantity,
                executed_price=result.avg_executed_price,
                fee=result.fee,
                fee_rate=fee_rate,
                fee_currency=result.fee_currency,
                executed_at=result.executed_at,
            )

            # 이벤트 기록
            await self._order_repo.create_event(
                trade_order_id=order.id,
                event_type="status_changed",
                from_status="pending",
                to_status=new_status,
                detail={
                    "exchange_order_id": result.exchange_order_id,
                    "executed_quantity": str(result.executed_quantity),
                },
            )

        except ExchangeError as exc:
            # 6. 실패: FAILED로 전이
            await self._order_repo.update_status(order.id, "failed")
            raise self._map_exchange_error(exc)
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass

        return await self._build_order_response(order.id)

    # ── 주문 목록 ──────────────────────────────────────────────────────

    async def list_orders(
        self, user_id: UUID, query: OrderListQuery,
    ) -> PaginatedOrders:
        """사용자 주문 내역 조회 (필터 + 페이지네이션)."""
        orders, total = await self._order_repo.list_by_user(
            user_id=user_id,
            exchange_account_id=query.exchange_account_id,
            coin_id=query.coin_id,
            status=query.status,
            side=query.side,
            from_dt=query.from_dt,
            to_dt=query.to_dt,
            page=query.page,
            size=query.size,
        )
        items = [self._to_response(o) for o in orders]
        pages = -(-total // query.size)  # ceil division
        return PaginatedOrders(
            items=items, total=total, page=query.page,
            size=query.size, pages=pages,
        )

    # ── 주문 상세 ──────────────────────────────────────────────────────

    async def get_order(
        self, user_id: UUID, order_id: UUID,
    ) -> OrderResponse:
        """단일 주문 상세 조회."""
        order = await self._order_repo.get_by_id_with_coin(order_id)
        if order is None or order.user_id != user_id:
            raise OrderErrors.not_found()
        return self._to_response(order)

    # ── 주문 취소 ──────────────────────────────────────────────────────

    async def cancel_order(
        self, user_id: UUID, order_id: UUID,
    ) -> OrderResponse:
        """단건 주문 취소.

        1. 소유권 + 취소 가능 상태 확인
        2. Provider 취소 API 호출
        3. 상태 전이 → CANCELLED (부분 체결 보존)
        """
        order = await self._order_repo.get_by_id_with_coin(order_id)
        if order is None or order.user_id != user_id:
            raise OrderErrors.not_found()

        if not OrderStateMachine.can_cancel(order.status):
            raise OrderErrors.cannot_cancel(order.status)

        # PENDING 상태 (아직 거래소 미전송) → DB만 업데이트
        if order.status == "pending":
            await self._order_repo.update_status(order.id, "cancelled")
            return await self._build_order_response(order.id)

        # OPEN/PARTIAL → 거래소 취소 API 호출
        account = await self._exchange_account_repo.get_by_id(
            order.exchange_account_id
        )
        provider = None
        try:
            enc_key = bytes.fromhex(self._settings.EXCHANGE_API_KEY_SECRET)
            provider = await self._factory.create_from_account(account, enc_key)

            success = await provider.cancel_order(
                order.coin.market_code, order.exchange_order_id
            )

            if success:
                await self._order_repo.update_status(order.id, "cancelled")
            else:
                # 이미 체결된 주문 → 상태 동기화
                await self._order_repo.update_status(order.id, "filled")

        except ExchangeError as exc:
            raise self._map_exchange_error(exc)
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass

        return await self._build_order_response(order.id)

    # ── 일괄 취소 ──────────────────────────────────────────────────────

    async def batch_cancel(
        self, user_id: UUID, request: BatchCancelRequest,
    ) -> BatchCancelResponse:
        """미체결 주문 일괄 취소 (부분 성공 허용).

        asyncio.gather로 병렬 처리, 개별 실패는 failed 목록에 포함.
        """
        success_ids: list[UUID] = []
        failures: list[BatchCancelFailure] = []

        # 소유권 일괄 확인
        orders = await self._order_repo.get_by_ids(request.order_ids)
        order_map = {o.id: o for o in orders}

        for oid in request.order_ids:
            if oid not in order_map or order_map[oid].user_id != user_id:
                failures.append(BatchCancelFailure(
                    order_id=oid, reason="주문을 찾을 수 없습니다."
                ))

        cancellable_ids = [
            oid for oid in request.order_ids
            if oid in order_map
            and order_map[oid].user_id == user_id
            and OrderStateMachine.can_cancel(order_map[oid].status)
        ]

        # 취소 불가 상태 필터링
        for oid in request.order_ids:
            if (
                oid in order_map
                and order_map[oid].user_id == user_id
                and not OrderStateMachine.can_cancel(order_map[oid].status)
            ):
                failures.append(BatchCancelFailure(
                    order_id=oid,
                    reason=f"취소 불가 상태: {order_map[oid].status}",
                ))

        # 병렬 취소
        async def _cancel_single(oid: UUID) -> UUID | BatchCancelFailure:
            try:
                await self.cancel_order(user_id, oid)
                return oid
            except AppError as e:
                return BatchCancelFailure(order_id=oid, reason=e.message)

        results = await asyncio.gather(
            *[_cancel_single(oid) for oid in cancellable_ids],
            return_exceptions=True,
        )

        for r in results:
            if isinstance(r, UUID):
                success_ids.append(r)
            elif isinstance(r, BatchCancelFailure):
                failures.append(r)
            elif isinstance(r, Exception):
                failures.append(BatchCancelFailure(
                    order_id=UUID(int=0), reason=str(r)
                ))

        return BatchCancelResponse(
            success_count=len(success_ids),
            failed_count=len(failures),
            success_ids=success_ids,
            failed=failures,
        )

    # ── Private 헬퍼 ───────────────────────────────────────────────────

    async def _build_order_response(self, order_id: UUID) -> OrderResponse:
        """TradeOrder + Coin JOIN 조회 → OrderResponse 변환.

        create_order/cancel_order 완료 후 최신 상태를 DB에서 재조회하여 응답.
        """
        order = await self._order_repo.get_by_id_with_coin(order_id)
        return self._to_response(order)

    @staticmethod
    def _to_response(order: TradeOrder) -> OrderResponse:
        """TradeOrder ORM → OrderResponse 스키마 변환."""
        return OrderResponse(
            id=order.id,
            exchange_account_id=order.exchange_account_id,
            coin_id=order.coin_id,
            coin_symbol=order.coin.symbol,
            exchange_type=order.coin.exchange_type,
            side=order.order_type,
            method=order.order_method,
            status=order.status,
            price=order.price,
            quantity=order.quantity,
            amount=order.amount,
            executed_quantity=order.executed_quantity,
            executed_price=order.executed_price,
            fee=order.fee,
            fee_rate=order.fee_rate,
            fee_currency=order.fee_currency,
            exchange_order_id=order.exchange_order_id,
            is_ai_order=order.is_ai_order,
            created_at=order.created_at,
            updated_at=order.updated_at,
            executed_at=order.executed_at,
        )

    @staticmethod
    def _build_provider_order(
        market_code: str, request: CreateOrderRequest,
    ) -> Order:
        """CreateOrderRequest → providers/types.py Order 변환.

        시장가 매수: price = amount (KRW 총액), quantity = 0 (placeholder)
        """
        if request.method == OrderMethod.MARKET and request.side == OrderSide.BUY:
            return Order(
                market=market_code,
                side=OrderSide.BUY,
                method=OrderMethod.MARKET,
                quantity=Decimal("0"),
                price=request.amount,  # Upbit: ord_type=price, price=KRW
            )
        return Order(
            market=market_code,
            side=request.side,
            method=request.method,
            quantity=request.quantity,
            price=request.price,
        )

    @staticmethod
    def _determine_status(result: OrderResult) -> str:
        """OrderResult → DB status 결정."""
        if result.status == OrderStatus.FILLED:
            return "filled"
        elif result.status == OrderStatus.PARTIAL:
            return "partial"
        else:
            return "open"

    @staticmethod
    def _map_exchange_error(exc: ExchangeError) -> AppError:
        """거래소 Provider 예외 → HTTP 응답용 AppError 변환."""
        match exc:
            case ExchangeInsufficientBalanceError():
                return OrderErrors.insufficient_balance()
            case ExchangeUnavailableError():
                return OrderErrors.exchange_unavailable()
            case ExchangeRateLimitError() as e:
                return ExchangeErrors.rate_limited(e.exchange, e.retry_after_seconds)
            case ExchangeAuthError() as e:
                return ExchangeErrors.auth_failed(e.exchange)
            case ExchangePermissionError() as e:
                return ExchangeErrors.permission_denied(e.exchange, "TRADE")
            case ExchangeOrderError() as e:
                return OrderErrors.exchange_order_failed(str(e))
            case _:
                return OrderErrors.exchange_order_failed("알 수 없는 거래소 오류")
```

---

## 11. Repository 계층 상세

### 11.1 OrderRepository

```python
class OrderRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self, *, user_id: UUID, exchange_account_id: UUID,
        coin_id: UUID, order_type: str, order_method: str,
        price: Decimal | None, quantity: Decimal | None,
        amount: Decimal | None, status: str,
        is_ai_order: bool = False,
    ) -> TradeOrder:
        """TradeOrder INSERT."""

    async def get_by_id(self, order_id: UUID) -> TradeOrder | None:
        """PK 조회."""

    async def get_by_id_with_coin(self, order_id: UUID) -> TradeOrder | None:
        """selectinload(TradeOrder.coin) 포함 조회."""

    async def get_by_ids(self, order_ids: list[UUID]) -> list[TradeOrder]:
        """IN 조회 (batch-cancel용). selectinload(coin) 포함."""

    async def list_by_user(
        self, *, user_id: UUID,
        exchange_account_id: UUID | None = None,
        coin_id: UUID | None = None,
        status: str | None = None,
        side: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        page: int = 1, size: int = 20,
    ) -> tuple[list[TradeOrder], int]:
        """사용자별 주문 목록 + COUNT.

        인덱스 활용:
        - user_id + status: ix_trade_orders_user_status_created
        - user_id + exchange_account_id + status: ix_trade_orders_user_account_status_created (신규)
        ORDER BY created_at DESC, OFFSET + LIMIT.
        """

    async def update_status(
        self, order_id: UUID, status: str,
    ) -> None:
        """상태만 업데이트."""

    async def update_after_execution(
        self, *, order_id: UUID, status: str,
        exchange_order_id: str | None = None,
        executed_quantity: Decimal | None = None,
        executed_price: Decimal | None = None,
        fee: Decimal | None = None,
        fee_rate: Decimal | None = None,
        fee_currency: str | None = None,
        executed_at: datetime | None = None,
    ) -> None:
        """주문 실행 후 상태 + 체결 정보 일괄 업데이트."""

    async def get_coin(self, coin_id: UUID) -> "Coin | None":
        """Coin 단건 조회 (주문 생성 시 market_code 확보용)."""

    async def get_trading_fee(
        self, exchange_type: str, tier: int = 0,
    ) -> "TradingFeeModel | None":
        """trading_fees 테이블에서 수수료율 조회."""

    async def get_open_orders_for_account(
        self, user_id: UUID, exchange_account_id: UUID,
    ) -> list[TradeOrder]:
        """계정별 미체결 주문 조회.

        WHERE status IN ('pending', 'open', 'partial')
        인덱스: ix_trade_orders_active (PARTIAL)
        """

    async def create_event(
        self, *, trade_order_id: UUID, event_type: str,
        from_status: str | None = None, to_status: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """TradeOrderEvent INSERT (상태 변경 이력 기록)."""
```

---

## 12. DB 스키마 변경

### 12.1 TradeOrder 모델 변경

**신규 컬럼** (Migration 필요):

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `amount` | Numeric(20, 8) nullable | 시장가 매수 KRW 총액 |
| `executed_price` | Numeric(20, 8) nullable | 평균 체결 가격 |
| `fee_rate` | Numeric(10, 6) nullable | 적용 수수료율 (감사/이상 탐지용) |
| `fee_currency` | String(10) nullable | 수수료 통화 (KRW, BTC, BNB 등) |

**기존 컬럼 변경**:

| 컬럼 | 변경 | 이유 |
|------|------|------|
| `quantity` | `nullable=True` | 시장가 매수 시 수량 미지정 |
| `status` CHECK | `'open'`, `'failed'` 추가 | 상태 머신 확장 |

### 12.2 trading_fees 테이블 (신규)

```python
class TradingFee(Base):
    __tablename__ = "trading_fees"
    __table_args__ = (
        UniqueConstraint(
            "exchange_type", "fee_tier",
            name="uq_trading_fee_exchange_tier",
        ),
        CheckConstraint("fee_tier >= 0", name="ck_trading_fee_tier"),
        CheckConstraint(
            "maker_rate >= 0 AND taker_rate >= 0",
            name="ck_trading_fee_rates",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    exchange_type: Mapped[str] = mapped_column(String(20), nullable=False)
    fee_tier: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False,
    )
    maker_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    taker_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    min_volume_krw: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 0), nullable=True,
    )
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
```

### 12.3 trade_order_events 테이블 (신규)

> db-architect 권장: 전자금융거래법 기준 주문 상태 변경 이력 5년 보존 의무.
> MongoDB audit_logs는 감사(IP, UA) 목적이므로 보완적 역할 — 중복 아님.

```python
class TradeOrderEvent(Base):
    __tablename__ = "trade_order_events"
    __table_args__ = (
        Index("ix_trade_order_events_order_id", "trade_order_id"),
        Index("ix_trade_order_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    trade_order_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("trade_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(30), nullable=False,
    )  # created, status_changed, filled, cancelled, failed, synced
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    trade_order: Mapped["TradeOrder"] = relationship(
        "TradeOrder", back_populates="events",
    )
```

TradeOrder 모델에 역참조 추가:
```python
# models/trading.py — TradeOrder 클래스에 추가
events: Mapped[list["TradeOrderEvent"]] = relationship(
    "TradeOrderEvent", back_populates="trade_order",
    cascade="all, delete-orphan",
)
```

**초기 데이터** (Migration INSERT):
| exchange_type | fee_tier | maker_rate | taker_rate | description |
|---------------|----------|------------|------------|-------------|
| upbit | 0 | 0.000500 | 0.000500 | 일반 (0.05%) |
| coinone | 0 | 0.000200 | 0.000200 | 포트폴리오 (0.02%) |
| coinbase | 0 | 0.006000 | 0.006000 | 일반 (0.6%) |
| binance | 0 | 0.001000 | 0.001000 | 일반 (0.1%) |

### 12.4 인덱스 변경

**신규 인덱스** (3개):

```python
# 추가 1: 계정별 주문 목록 (exchange_account_id 필터 커버)
Index(
    "ix_trade_orders_user_account_status_created",
    "user_id", "exchange_account_id", "status", "created_at",
)

# 추가 2: 거래소 주문 ID 유니크 (상태 동기화 + 중복 방지)
Index(
    "ix_trade_orders_exchange_order_id_unique",
    "exchange_account_id", "exchange_order_id",
    unique=True,
    postgresql_where=text("exchange_order_id IS NOT NULL"),
)

# 추가 3: 계정별 미체결(active) 주문 bulk 취소 (PARTIAL INDEX)
Index(
    "ix_trade_orders_active",
    "user_id", "exchange_account_id",
    postgresql_where=text("status IN ('pending', 'open', 'partial')"),
)
```

**기존 partial 인덱스 수정**:
```python
# 기존: postgresql_where=text("status = 'pending'")
# 변경: postgresql_where=text("status IN ('pending', 'open', 'partial')")
Index(
    "ix_trade_orders_pending",
    "user_id", "created_at",
    postgresql_where=text("status IN ('pending', 'open', 'partial')"),
)
```

### 12.5 Alembic 마이그레이션

파일: `server/alembic/versions/006_v1_14_order_trading.py`

변경 내용:
1. `trade_orders` CHECK 제약 DROP + 재생성 (`'open'`, `'failed'` 추가)
2. `trade_orders` 컬럼 추가: `amount`, `executed_price`, `fee_rate`, `fee_currency`
3. `trade_orders.quantity` nullable 변경
4. 기존 `ix_trade_orders_pending` DROP + `ix_trade_orders_active` 재생성 (WHERE 조건 확장: pending, open, partial)
5. 신규 인덱스 3개 CREATE (user_account_status_created, exchange_order_id unique partial, active)
6. `trading_fees` 테이블 CREATE
7. `trade_order_events` 테이블 CREATE
8. 초기 수수료 데이터 INSERT (upbit, coinone, coinbase, binance)

---

## 13. 쿼리 패턴별 인덱스 활용

| 쿼리 패턴 | 사용 인덱스 |
|-----------|-------------|
| 주문 생성 (INSERT) | PK |
| 주문 목록 (user + status + 최신순) | `ix_trade_orders_user_status_created` |
| 주문 목록 (user + account + status) | `ix_trade_orders_user_account_status_created` (신규) |
| 주문 상세 (UUID) | PK |
| 주문 취소 (단건 PK 조회) | PK |
| 일괄 취소 (계정별 미체결) | `ix_trade_orders_active` (신규 PARTIAL) |
| 상태 동기화 (exchange_order_id) | `ix_trade_orders_exchange_order_id_unique` (신규) |
| 수수료 조회 | `uq_trading_fee_exchange_tier` (trading_fees) |

---

## 14. 거래소 실시간 동기화

### 14.1 동기화 범위 (v1-14)

v1-14에서는 **요청 시점 동기화** (Passive Sync)만 구현:
- 주문 상세 조회 시 `exchange_order_id`가 있으면 거래소에서 최신 상태 확인 가능
- 주문 취소 시 거래소 응답으로 실제 상태 반영

**능동적 동기화** (Active Sync — WS 이벤트 기반)는 v2 범위:
- 거래소 WS에서 체결 이벤트 수신 → DB 자동 업데이트
- Celery 주기적 폴링 (fallback)

### 14.2 Redis 키 추가

```python
# redis_keys.py 추가
class RedisKey:
    @staticmethod
    def trading_fee(exchange: str, tier: int = 0) -> str:
        return f"fee:{exchange}:{tier}"

class RedisTTL:
    TRADING_FEE = 3600  # 1시간
```

---

## 15. API 엔드포인트 코드

```python
# server/app/api/v1/orders.py
router = APIRouter()


@router.post("/batch-cancel", response_model=ApiResponse[BatchCancelResponse])
async def batch_cancel_orders(
    body: BatchCancelRequest,
    request: Request,
    current_user: CurrentUser,
    service: OrderServiceDep,
    audit: AuditServiceDep,
) -> ApiResponse[BatchCancelResponse]:
    """미체결 주문 일괄 취소."""
    result = await service.batch_cancel(current_user.id, body)
    if result.success_count > 0:
        await audit.log(
            action=AuditAction.ORDER_BATCH_CANCELLED,
            ip_address=_get_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
            user_id=current_user.id,
            details={
                "success_count": result.success_count,
                "failed_count": result.failed_count,
            },
        )
    return ApiResponse(data=result)


@router.post("", response_model=ApiResponse[OrderResponse], status_code=201)
async def create_order(
    body: CreateOrderRequest,
    request: Request,
    current_user: CurrentUser,
    service: OrderServiceDep,
    audit: AuditServiceDep,
) -> ApiResponse[OrderResponse]:
    """주문 생성 (시장가/지정가)."""
    order = await service.create_order(current_user.id, body)
    await audit.log(
        action=AuditAction.ORDER_CREATED,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={
            "order_id": str(order.id),
            "side": body.side.value,
            "method": body.method.value,
        },
    )
    return ApiResponse(data=order)


@router.get("", response_model=ApiResponse[PaginatedOrders])
async def list_orders(
    current_user: CurrentUser,
    service: OrderServiceDep,
    exchange_account_id: UUID | None = None,
    coin_id: UUID | None = None,
    status: OrderStatus | None = None,
    side: OrderSide | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> ApiResponse[PaginatedOrders]:
    """주문 내역 조회."""
    query = OrderListQuery(
        exchange_account_id=exchange_account_id,
        coin_id=coin_id,
        status=status,
        side=side,
        from_dt=from_dt,
        to_dt=to_dt,
        page=page,
        size=size,
    )
    result = await service.list_orders(current_user.id, query)
    return ApiResponse(data=result)


@router.get("/{order_id}", response_model=ApiResponse[OrderResponse])
async def get_order(
    order_id: UUID,
    current_user: CurrentUser,
    service: OrderServiceDep,
) -> ApiResponse[OrderResponse]:
    """주문 상세 조회."""
    order = await service.get_order(current_user.id, order_id)
    return ApiResponse(data=order)


@router.delete("/{order_id}", response_model=ApiResponse[OrderResponse])
async def cancel_order(
    order_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: OrderServiceDep,
    audit: AuditServiceDep,
) -> ApiResponse[OrderResponse]:
    """주문 취소."""
    order = await service.cancel_order(current_user.id, order_id)
    await audit.log(
        action=AuditAction.ORDER_CANCELLED,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={"order_id": str(order_id)},
    )
    return ApiResponse(data=order)
```

---

## 16. 구현 순서 및 의존성

```
ST1: 스캐폴딩
 │   models/trading_fee.py, schemas/order.py, repositories/order_repository.py,
 │   services/order_service.py (OrderStateMachine 포함), api/v1/orders.py
 │   + deps.py DI + __init__.py 라우터 등록 + OrderErrors
 │   + providers/enums.py (OPEN, FAILED 추가)
 │   + Migration 006
 │
 ├── ST2: OrderRepository CRUD + OrderStateMachine 단위 테스트
 │    │
 │    └── ST3: OrderService.create_order() + POST /api/v1/orders
 │         │
 │         ├── ST4: OrderService.list_orders() + GET /api/v1/orders
 │         │
 │         ├── ST5: OrderService.get_order() + GET /api/v1/orders/{order_id}
 │         │
 │         ├── ST6: OrderService.cancel_order() + DELETE /api/v1/orders/{order_id}
 │         │    │
 │         │    └── ST7: OrderService.batch_cancel() + POST /api/v1/orders/batch-cancel
 │         │
 │         └── ST8: 수수료 계산 로직 (_calculate_fee + trading_fees 테이블 연동)
 │
 └── ST9: 예외 처리 전략 (_map_exchange_error + 재시도 로직)
      │
      └── ST10: 통합 테스트 + 코드 리뷰
```

---

## 17. 테스트 전략

### 17.1 단위 테스트 (예상 35건)

| 대상 | 테스트 항목 |
|------|------------|
| OrderStateMachine | 유효 전이 6개, 무효 전이 5개, can_cancel 각 상태별 |
| OrderRepository | create, get_by_id, list_by_user (필터 조합), update_status, update_after_execution, get_open_orders_for_account |
| OrderService | create_order (시장가 매수/매도, 지정가), cancel_order (성공/이미 체결/취소 불가), batch_cancel (전체 성공/부분 성공/전체 실패) |
| OrderService (에러) | 계정 미존재, 코인 미존재, 잔고 부족, 거래소 불가, 권한 부족 |

### 17.2 통합 테스트 (예상 20건)

| 엔드포인트 | 테스트 항목 |
|-----------|------------|
| POST /orders | 시장가 매수 201, 시장가 매도 201, 지정가 201, 422 (검증 실패), 401 (미인증), 잔고 부족 422, 거래소 불가 503 |
| GET /orders | 목록 조회 200, 상태 필터, 계정 필터, 페이지네이션, 빈 결과 |
| GET /orders/{id} | 정상 200, 404 (미존재), 404 (타인 주문) |
| DELETE /orders/{id} | 취소 200, 422 (이미 체결), 404 |
| POST /orders/batch-cancel | 전체 성공, 부분 성공, 빈 목록 422 |

---

## 18. 설계 결정 요약 (ADR)

### ADR-14-1: OrderService 통합 vs 분리

| 항목 | 결정 |
|------|------|
| 선택 | 단일 `OrderService` (생성/조회/취소 통합) |
| 대안 | `OrderExecutionService` + `OrderQueryService` 분리 |
| 이유 | CoinService 패턴 일관성, 주문 관련 DI가 동일 (repo, factory, settings). Repository만 분리하여 SRP 유지. |

### ADR-14-2: 상태 머신 배치

| 항목 | 결정 |
|------|------|
| 선택 | `OrderStateMachine` 클래스를 `order_service.py` 내 모듈 레벨에 배치 |
| 대안 | `trading/state_machine.py` 별도 모듈 |
| 이유 | OrderService에서만 사용, 코드 20줄 미만으로 별도 패키지 생성 불필요 |

### ADR-14-3: 시장가 매수 필드 설계

| 항목 | 결정 |
|------|------|
| 선택 | `amount` 필드 신규 추가 (KRW 총액), `quantity` nullable 변경 |
| 대안 | `price` 필드에 KRW 총액 저장 (Upbit API 방식) |
| 이유 | `price`는 "단가" 의미가 강함. `amount`(총액)과 `price`(단가) 분리가 API 사용자에게 명확. |

### ADR-14-4: 예외 매핑 위치

| 항목 | 결정 |
|------|------|
| 선택 | `OrderService._map_exchange_error()` 정적 메서드 |
| 대안 | 별도 `adapters/exchange_error_adapter.py` 모듈 |
| 이유 | ExchangeAccountService._verify_with_provider()와 동일 패턴. 매핑 규칙이 단순하여 별도 모듈 불필요. |

### ADR-14-5: 일괄 취소 방식

| 항목 | 결정 |
|------|------|
| 선택 | `asyncio.gather` 병렬 처리 + 부분 성공 허용 |
| 대안 | 순차 처리 (하나 실패 시 전체 롤백) |
| 이유 | 거래소 API 호출이 독립적. 하나의 실패가 다른 취소를 막으면 안 됨. 부분 성공 응답으로 클라이언트가 실패 건 재처리 가능. |

### ADR-14-6: 실시간 동기화 범위

| 항목 | 결정 |
|------|------|
| 선택 | v1-14는 요청 시점 동기화 (Passive Sync)만 구현 |
| 대안 | WS 이벤트 기반 능동 동기화 |
| 이유 | 능동 동기화는 WS 주문 체결 이벤트 구독 + 상태 매칭 로직이 복잡. v1-14 범위를 초과하므로 v2로 연기. |

### ADR-14-7: 수수료 테이블

| 항목 | 결정 |
|------|------|
| 선택 | `trading_fees` 테이블 신규 + Provider 우선 조회 + DB fallback |
| 대안 | Provider API만 사용 (DB 없음) |
| 이유 | 거래소 API 실패 시 수수료 계산 불가 방지. 초기 데이터로 즉시 사용 가능. Redis 캐시 계층 추가로 DB 부하 최소화. |

---

## 19. 코드 패턴 참조

기존 v1-11/v1-13 패턴 일관성 유지:
- API: `ApiResponse[T]` 래핑, `CurrentUser` DI, `AuditService` 로깅
- Repository: `AsyncSession` 주입, `select`/`update`/`delete`, `selectinload` eager loading
- Service: Repository + Factory + Settings 주입, `AppError` 도메인 예외
- DI: `Depends(get_xxx)` + `Annotated[T, Depends()]`, lazy import
- 에러: `OrderErrors` 팩토리 패턴 (AuthErrors, ExchangeErrors, CoinErrors와 동일)
- 라우터: `router = APIRouter()`, `__init__.py`에서 prefix 포함 등록
- Provider 사용: `factory.create_from_account()` → try/finally → `provider.close()`
