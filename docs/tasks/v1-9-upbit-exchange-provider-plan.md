# v1-9 Upbit 거래소 프로바이더 구현 — 설계서

> **작성**: project-architect (시스템 아키텍처/흐름/구현계획), code-architect (코드 구조/API 규격/인터페이스 설계)
> **대상 태스크**: v1-9 — Upbit REST API + WebSocket 구현, JWT 인증, 실시간 시세/호가 수신
> **현재 상태**: 구현 완료 (2026-03-13) — 38/38 테스트 통과, 코드 리뷰 LGTM

---

## 1. 개요

v1-8에서 구축한 거래소 추상화 계층(BaseExchangeProvider, ExchangeProviderRegistry) 위에 Upbit 거래소 구체 구현체를 작성한다.

**의존성**: v1-8 (Exchange Abstraction Layer) 완료.

**구현 범위**:
- Upbit REST API 7개 메서드 (get_ticker, get_orderbook, get_candles, place_order, cancel_order, get_balance, get_trading_fee, verify_api_key)
- Upbit WebSocket 2개 채널 (ticker, orderbook), 자동 재연결
- JWT HS512 인증 (api_key + api_secret, query_hash 포함)
- Upbit 에러 코드 → ExchangeError 계층 매핑

---

## 2. 파일/모듈 구조

### 2.1 신규 파일 목록

```
server/app/providers/upbit/
├── __init__.py        # UpbitProvider 공개 노출
├── auth.py            # UpbitJwtAuth (JWT HS512 생성 유틸리티)
├── constants.py       # URL, 타임프레임 매핑, Upbit 에러 코드 매핑, 정적 마켓 목록(fallback)
├── mappers.py         # Upbit API 응답 → 공통 모델 변환 순수함수 (상태 없음)
├── provider.py        # UpbitProvider (BaseExchangeProvider 상속, 핵심 구현)
└── stream.py          # _UpbitWebSocketClient (WS 연결 관리, provider.py가 컴포지션으로 사용)
```

> **JWT 알고리즘**: Upbit 공식 문서 기준 JWT 서명은 **HS512**(HMAC-SHA512). Secret Key는 Base64 인코딩 없이 원본 그대로 사용.
>
> **`stream.py` 명칭 근거**: `ExchangeStreamProvider` ABC와 명칭 일관성 유지. `websocket.py` 대신 `stream.py`를 사용하여 `websockets` 라이브러리명 충돌을 방지한다.
>
> **`mappers.py` 분리 근거**: Upbit 응답 필드 파싱은 거래소 고유 로직이므로 독립 모듈로 분리해 단위 테스트 가능하게 한다. 모든 함수는 순수함수 `parse_ticker(data: dict) -> Ticker` 형태.

### 2.2 기존 파일 수정

| 파일 | 수정 내용 |
|------|----------|
| `server/app/providers/__init__.py` | `from .upbit import UpbitProvider` 추가 (자동 등록 트리거) |
| `server/app/providers/types.py` | `SymbolMapper._MAPS[ExchangeType.UPBIT]` — 주요 마켓 심볼 확장 |
| `server/app/providers/factory.py` | `register_defaults()` — UPBIT은 MockProvider 대신 UpbitProvider 등록 변경 |

### 2.3 클래스 계층도

```
ExchangeProvider (ABC)
└── BaseExchangeProvider (Rate Limiter + Circuit Breaker 주입)
    └── UpbitProvider                    ← 신규 구현체
            ├── _auth: UpbitJwtAuth      ← 컴포지션 (JWT 생성)
            └── _ws: _UpbitWebSocketClient ← 컴포지션 (WS 연결/구독)
```

> **설계 근거**: WS 로직을 `_UpbitWebSocketClient`로 분리하여 단일 클래스 비대화를 방지하고 WS 재연결 로직을 독립적으로 테스트 가능하게 한다.

---

## 3. 모듈 상세 설계

### 3.1 `auth.py` — UpbitJwtAuth

```python
class UpbitJwtAuth:
    """Upbit HMAC-SHA512 JWT 토큰 생성기.

    Upbit 인증 방식:
    - 공개 API (시세/호가/캔들): 인증 불필요
    - 비공개 API (주문/잔고): Authorization: Bearer {JWT}
    - JWT Header: {"alg": "HS512", "typ": "JWT"}
    - JWT Payload: { access_key, nonce (UUID4) }
    - query params 있는 경우: payload에 query_hash (SHA-512 hex), query_hash_alg: "SHA512" 추가
    - POST body 있는 경우: body를 "key=value&key=value" 형식으로 변환 후 SHA-512 해시
    - Secret Key는 Base64 인코딩되어 있지 않으므로 그대로 사용
    """

    def __init__(self, api_key: str, api_secret: str) -> None: ...

    def generate(self, query_params: dict[str, str] | None = None) -> str:
        """Bearer 토큰 문자열 생성 (prefix 없음, 헤더에서 f"Bearer {token}" 사용).

        Args:
            query_params: DELETE /v1/order 등 query string 있는 요청 시 전달.
                          내부에서 SHA-512 query_hash로 변환.

        Implementation:
            payload = {"access_key": self._api_key, "nonce": str(uuid.uuid4())}
            if query_params:
                query_string = urlencode(query_params)
                payload["query_hash"] = hashlib.sha512(query_string.encode()).hexdigest()
                payload["query_hash_alg"] = "SHA512"
            return jwt.encode(payload, self._api_secret, algorithm="HS512")
        """

    def generate_for_body(self, json_body: dict) -> str:
        """POST body가 있는 요청용 JWT 생성.

        body를 "key=value&key=value" 형식으로 변환 후 query_hash 생성.
        """

    def authorization_header(self, query_params: dict[str, str] | None = None) -> dict[str, str]:
        """{"Authorization": "Bearer {token}"} 딕셔너리 반환."""

    def _build_query_hash(self, params: dict[str, str]) -> str:
        """query string을 SHA-512 hex digest로 변환."""
```

### 3.2 `constants.py` — 상수 및 매핑

```python
# REST / WebSocket URL
UPBIT_REST_BASE_URL: str = "https://api.upbit.com/v1"
UPBIT_WS_URL: str = "wss://api.upbit.com/websocket/v1"

# 타임프레임 → Upbit candle 엔드포인트 경로 매핑
# Upbit은 /candles/minutes/{unit}, /candles/days, /candles/weeks, /candles/months 지원
# "1h" → "minutes/60" (Upbit은 hours 엔드포인트 미제공)
TIMEFRAME_TO_CANDLE_PATH: dict[str, str] = {
    "1m":  "minutes/1",
    "3m":  "minutes/3",
    "5m":  "minutes/5",
    "15m": "minutes/15",
    "30m": "minutes/30",
    "1h":  "minutes/60",
    "4h":  "minutes/240",
    "1d":  "days",
    "1w":  "weeks",
    "1M":  "months",
}

# Upbit 에러 코드 → ExchangeError 서브클래스 매핑
# Upbit 에러 응답 형식: { "error": { "name": "...", "message": "..." } }
UPBIT_ERROR_MAP: dict[str, type[ExchangeError]] = {
    "invalid_access_key":        ExchangeAuthError,
    "expired_access_key":        ExchangeAuthError,
    "nonce_used":                ExchangeAuthError,      # nonce 재사용 공격 방지
    "no_authorization_ip":       ExchangePermissionError, # IP whitelist 제한
    "exceed_order_limit":        ExchangeRateLimitError,
    "exceed_api_limit":          ExchangeRateLimitError,
    "insufficient_funds_ask":    ExchangeInsufficientBalanceError,  # 매도 잔고 부족
    "insufficient_funds_bid":    ExchangeInsufficientBalanceError,  # 매수 잔고 부족
    "under_min_total_ask":       ExchangeOrderError,     # 최소 주문금액 미달 (매도)
    "under_min_total_bid":       ExchangeOrderError,     # 최소 주문금액 미달 (매수)
    "unknown_market":            ExchangeInvalidSymbolError,
    "validation_error":          ExchangeOrderError,
    "create_ask_error":          ExchangeOrderError,
    "create_bid_error":          ExchangeOrderError,
    # 추가 인증 에러 (Upbit 공식 문서 기준)
    "jwt_verification":          ExchangeAuthError,
    "no_authorization_token":    ExchangeAuthError,
    "out_of_scope":              ExchangePermissionError,
}

# HTTP 상태 코드 기반 폴백 매핑 (error.name 매칭 실패 시)
HTTP_STATUS_ERROR_MAP: dict[int, type[ExchangeError]] = {
    401: ExchangeAuthError,
    403: ExchangePermissionError,
    404: ExchangeInvalidSymbolError,
    418: ExchangeRateLimitError,    # Upbit 고유: 과도한 요청 시 IP 차단
    429: ExchangeRateLimitError,
}

# Upbit → 공통 OrderStatus 매핑
# Upbit 주문 상태: wait | watch | done | cancel
UPBIT_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "wait":   OrderStatus.PENDING,
    "watch":  OrderStatus.PENDING,
    "done":   OrderStatus.FILLED,
    "cancel": OrderStatus.CANCELLED,
}

# Upbit 수수료율 기본값 (verify_api_key 시점에 로드, get_trading_fee 에서 캐싱)
UPBIT_DEFAULT_FEE_RATE: Decimal = Decimal("0.0005")  # 0.05%

# 정적 마켓 목록 (initialize() 동적 로드 실패 시 fallback)
# GET /v1/market/all 성공 시 SymbolMapper._MAPS[UPBIT]를 동적으로 갱신
UPBIT_STATIC_MARKETS: dict[str, str] = {
    "BTC/KRW":  "KRW-BTC",
    "ETH/KRW":  "KRW-ETH",
    "XRP/KRW":  "KRW-XRP",
    "SOL/KRW":  "KRW-SOL",
    "ADA/KRW":  "KRW-ADA",
    "DOGE/KRW": "KRW-DOGE",
    "DOT/KRW":  "KRW-DOT",
    "AVAX/KRW": "KRW-AVAX",
    "MATIC/KRW":"KRW-MATIC",
    "LINK/KRW": "KRW-LINK",
    "ATOM/KRW": "KRW-ATOM",
    "NEAR/KRW": "KRW-NEAR",
    "TRX/KRW":  "KRW-TRX",
    "LTC/KRW":  "KRW-LTC",
    "BCH/KRW":  "KRW-BCH",
}
```

### 3.3 `mappers.py` — 응답 변환 순수함수

```python
"""Upbit API 응답 dict → 공통 Pydantic 모델 변환 순수함수 모음.

모든 함수:
- 상태(state)를 갖지 않음 (순수함수)
- 입력: Upbit API 응답 dict
- 출력: providers/types.py의 공통 모델
- 파싱 실패 시: ExchangeDataError raise
"""

def parse_ticker(data: dict) -> Ticker:
    """Upbit REST /v1/ticker 또는 WS ticker 응답 → Ticker 변환.

    REST 응답: 배열의 단일 원소 dict.
    WS 응답: type="ticker" 메시지 dict (필드명 동일, 일부 생략).

    Upbit 필드 매핑:
      trade_price           → price
      opening_price         → open_price
      high_price            → high_price
      low_price             → low_price
      acc_trade_volume_24h  → volume
      acc_trade_price_24h   → trade_value
      signed_change_rate    → change_rate
      trade_timestamp (ms)  → timestamp (UTC datetime)
      code / market         → market
    """

def parse_orderbook(data: dict, depth: int = 10) -> OrderBook:
    """Upbit REST /v1/orderbook 또는 WS orderbook 응답 → OrderBook 변환.

    orderbook_units[:depth]:
      ask_price, ask_size → asks (오름차순)
      bid_price, bid_size → bids (내림차순)
    """

def parse_candle(data: dict, market: str, timeframe: str) -> Candle:
    """Upbit REST /v1/candles/* 단일 캔들 dict → Candle 변환.

    Upbit 필드 매핑:
      candle_date_time_utc  → timestamp (fromisoformat + tzinfo=UTC)
      opening_price         → open
      high_price            → high
      low_price             → low
      trade_price           → close
      candle_acc_trade_volume → volume
    """

def parse_order_result(data: dict) -> OrderResult:
    """Upbit REST /v1/orders POST 응답 → OrderResult 변환.

    Upbit 필드 매핑:
      uuid              → exchange_order_id
      state             → status (UPBIT_ORDER_STATUS_MAP)
      volume            → quantity
      executed_volume   → executed_quantity
      price             → price
      avg_buy_price     → avg_executed_price (체결 시)
      paid_fee          → fee
      created_at        → created_at (ISO8601 with TZ)
    """

def parse_balance(data: dict) -> Balance:
    """Upbit REST /v1/accounts 단일 계좌 dict → Balance 변환.

    Upbit 필드 매핑:
      currency → currency
      balance  → available
      locked   → locked
    """
```

### 3.4 `provider.py` — UpbitProvider

#### 클래스 시그니처 및 __init__

```python
@ExchangeProviderRegistry.register(ExchangeType.UPBIT)
class UpbitProvider(BaseExchangeProvider):
    """Upbit 거래소 REST + WebSocket 구현체.

    BaseExchangeProvider를 상속하여 Rate Limiter + Circuit Breaker를
    모든 REST 호출에 자동 적용. 모든 REST 호출은 _execute_rest() 경유 필수.
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
        super().__init__(exchange_type, api_key, api_secret, rate_limiter, circuit_breaker, user_id)
        self._auth = UpbitJwtAuth(api_key, api_secret)
        self._ws: _UpbitWebSocketClient | None = None

    async def initialize(self) -> None:
        """HTTP 클라이언트 준비 + SymbolMapper 동적 갱신 (fallback 포함).

        1. super().initialize() — httpx 클라이언트 lazy init
        2. GET /v1/market/all → SymbolMapper._MAPS[UPBIT] 갱신
           실패 시 WARNING 로그 + UPBIT_STATIC_MARKETS fallback 유지
        """
        await super().initialize()
        try:
            await self._refresh_symbol_map()
        except ExchangeNetworkError:
            logger.warning(
                "Failed to load Upbit market list, using static fallback (%d markets)",
                len(UPBIT_STATIC_MARKETS),
            )

    async def _refresh_symbol_map(self) -> None:
        """GET /v1/market/all 호출 → SymbolMapper 갱신.

        Upbit 응답: [{"market": "KRW-BTC", "korean_name": "비트코인", ...}, ...]
        KRW 마켓만 필터링: "KRW-{BASE}" → "{BASE}/KRW"
        """
```

#### REST 메서드 — Upbit API 엔드포인트 매핑

| 메서드 | HTTP | Upbit 엔드포인트 | 인증 | 비고 |
|--------|------|----------------|------|------|
| `get_ticker(market)` | GET | `/v1/ticker?markets={market}` | 불필요 | 배열 응답[0] 사용 |
| `get_orderbook(market, depth)` | GET | `/v1/orderbook?markets={market}` | 불필요 | `orderbook_units[:depth]` 사용 |
| `get_candles(market, timeframe, count)` | GET | `/v1/candles/{path}?market={market}&count={count}` | 불필요 | `TIMEFRAME_TO_CANDLE_PATH` 매핑 |
| `place_order(order)` | POST | `/v1/orders` | 필요 | body JSON, 시장가 분기 처리 |
| `cancel_order(market, order_id)` | DELETE | `/v1/order?uuid={order_id}` | 필요 | query_hash JWT |
| `get_balance()` | GET | `/v1/accounts` | 필요 | 전체 계좌 목록 |
| `get_trading_fee(market)` | GET | `/v1/orders/chance?market={market}` | 필요 | ask_fee, bid_fee 추출 |
| `verify_api_key()` | GET | `/v1/api_keys` → `/v1/accounts` | 필요 | 2단계 권한 검증 |

#### place_order 주문 방식 분기

Upbit의 `ord_type` 필드는 세 값을 가진다. 공통 `Order` 모델의 `OrderSide` + `OrderMethod`로 매핑:

| Order.side | Order.method | Upbit side | Upbit ord_type | Upbit price 필드 | Upbit volume 필드 |
|------------|--------------|------------|----------------|-----------------|------------------|
| BUY | LIMIT | `bid` | `limit` | `order.price` | `order.quantity` |
| SELL | LIMIT | `ask` | `limit` | `order.price` | `order.quantity` |
| BUY | MARKET | `bid` | `price` | `order.price` (총 KRW 예산) | 없음 |
| SELL | MARKET | `ask` | `market` | 없음 | `order.quantity` |

> **주의**: Upbit 시장가 매수(BUY + MARKET)는 코인 수량이 아닌 **총 KRW 금액**을 입력받는다.
> `Order.price` 필드를 KRW 예산으로 재사용한다. 호출자는 이 컨벤션을 준수해야 한다.
> 서비스 레이어(`ExchangeService`)에서 이 변환 로직을 문서화해야 한다.

#### verify_api_key 2단계 검증

```
1. GET /v1/api_keys  → 성공 시 is_valid=True, 실패(401) 시 is_valid=False 반환
2. GET /v1/accounts  → 성공 시 VIEW_BALANCE 권한 추가
   실패(403) 시 VIEW_BALANCE 권한 없음
3. GET /v1/orders/chance?market=KRW-BTC → 성공 시 VIEW_ORDERS + TRADE 권한 추가
   실패(403) 시 해당 권한 없음
4. has_withdraw_permission: Upbit API로 출금 권한 확인 불가 → 항상 False
```

#### REST 헬퍼 메서드

```python
async def _request(
    self,
    method: str,      # "GET" | "POST" | "DELETE"
    path: str,        # "/v1/ticker" 등
    *,
    params: dict[str, str] | None = None,   # query string
    json_body: dict | None = None,           # POST body (JSON)
    auth: bool = False,                      # JWT 헤더 필요 여부
) -> Any:
    """HTTP 요청 실행 + Upbit 에러 응답 처리.

    JWT 생성 분기:
    - auth=False: Authorization 헤더 없음
    - auth=True, params 있음 (GET with query / DELETE):
        → self._auth.generate(query_params=params)  # query_hash 포함
    - auth=True, json_body 있음 (POST):
        → self._auth.generate_for_body(json_body)   # body query_hash 포함
    - auth=True, params/body 없음 (GET /v1/accounts 등):
        → self._auth.generate()                      # 기본 payload만

    httpx 예외 처리: TimeoutException, ConnectError → ExchangeNetworkError
    Upbit 에러 응답: _parse_upbit_error() 호출
    """

def _parse_upbit_error(self, status_code: int, body: dict) -> None:
    """Upbit 에러 응답을 ExchangeError 계층으로 변환 후 raise.

    Upbit 에러 형식: { "error": { "name": "...", "message": "..." } }
    UPBIT_ERROR_MAP에 없는 에러 코드: ExchangeDataError로 폴백.
    HTTP 429: ExchangeRateLimitError (Retry-After 헤더 파싱).
    httpx 네트워크 예외: ExchangeNetworkError로 변환.
    """
```

### 3.5 `stream.py` — _UpbitWebSocketClient

#### 클래스 구조

```python
class _UpbitWebSocketClient:
    """Upbit WebSocket 단일 연결 + 다중 채널 구독 관리.

    Upbit WS 특성:
    - 단일 연결에서 다중 type(ticker, orderbook) 동시 구독 가능
    - 구독 변경 시 새 subscription 메시지 전송 (연결 유지)
    - 인증 불필요 (ticker, orderbook은 public 데이터)
    - 응답 형식: JSON (format 미지정 시 기본 SIMPLE 포맷)

    재연결 전략:
    - Exponential Backoff with jitter
    - 초기 1s → 2s → 4s → 8s → max 60s
    - 최대 EXCHANGE_WS_RECONNECT_MAX(settings)회 시도
    """

    def __init__(self, reconnect_max: int = 5) -> None:
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._subscriptions: dict[str, dict] = {}  # type → {markets, callback}
        self._listen_task: asyncio.Task | None = None
        self._reconnect_max = reconnect_max
        self._connected = False

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def subscribe(
        self,
        sub_type: str,     # "ticker" | "orderbook"
        markets: list[str],
        callback: Callable,
    ) -> None:
        """구독 등록 + 즉시 subscription 메시지 전송.
        기존 같은 type 구독은 덮어쓴다.
        """

    async def unsubscribe(self, markets: list[str] | None = None) -> None:
        """특정 마켓 또는 전체 구독 해제."""

    @property
    def is_connected(self) -> bool: ...

    # 내부 메서드
    async def _connect_once(self) -> None: ...
    async def _connect_with_retry(self) -> None: ...
    async def _send_subscription_message(self) -> None:
        """현재 _subscriptions 상태 기반으로 Upbit WS 구독 메시지 전송.

        포맷:
        [
          {"ticket": "<uuid4>"},
          {"type": "ticker", "codes": ["KRW-BTC", ...], "is_only_realtime": true},
          {"type": "orderbook", "codes": ["KRW-BTC", ...]},
          {"format": "DEFAULT"}
        ]
        구독 없는 type은 메시지에서 제외.
        """
    async def _ping_loop(self) -> None:
        """주기적 PING 전송 (Upbit 120초 무통신 타임아웃 방지).

        EXCHANGE_WS_PING_INTERVAL(기본 30초) 간격으로 "PING" 문자열 전송.
        전송 실패 시 loop 종료 → _connect_with_retry()가 재연결 처리.
        """
    async def _listen_loop(self) -> None: ...
    async def _handle_message(self, raw: str | bytes) -> None:
        """수신 메시지 파싱 → type 필드 기반 분기 → mappers.py 함수 호출 → 콜백 실행.

        raw: 바이너리 또는 텍스트 JSON.
        type="ticker"    → mappers.parse_ticker(data) → ticker 콜백
        type="orderbook" → mappers.parse_orderbook(data) → orderbook 콜백
        type 미매칭      → 로그 경고 후 무시
        """
    @staticmethod
    def _decode_message(raw: bytes | str) -> dict:
        """바이너리/텍스트 JSON → dict 변환."""
```

#### WS 메시지 파싱 — Upbit 응답 필드 매핑

**Ticker 응답 (`type: "ticker"`):**

| Upbit 필드 | 공통 Ticker 필드 | 비고 |
|-----------|----------------|------|
| `code` | `market` | e.g. "KRW-BTC" |
| `trade_price` | `price` | 현재가 |
| `opening_price` | `open_price` | 당일 시가 |
| `high_price` | `high_price` | 당일 고가 |
| `low_price` | `low_price` | 당일 저가 |
| `acc_trade_volume_24h` | `volume` | 24h 거래량 |
| `acc_trade_price_24h` | `trade_value` | 24h 거래대금 |
| `signed_change_rate` | `change_rate` | 소수 변동률 |
| `trade_timestamp` | `timestamp` | epoch ms → UTC datetime |

**Orderbook 응답 (`type: "orderbook"`):**

| Upbit 필드 | 공통 OrderBook 필드 | 비고 |
|-----------|-------------------|------|
| `code` | `market` | |
| `orderbook_units[].ask_price` | `asks[].price` | |
| `orderbook_units[].ask_size` | `asks[].quantity` | |
| `orderbook_units[].bid_price` | `bids[].price` | |
| `orderbook_units[].bid_size` | `bids[].quantity` | |
| `timestamp` | `timestamp` | epoch ms |

---

## 4. API 엔드포인트 상세 매핑

### 4.1 GET /v1/ticker — get_ticker

```
요청: GET https://api.upbit.com/v1/ticker?markets=KRW-BTC
인증: 불필요
응답: [{
  "market": "KRW-BTC",
  "trade_price": 95000000.0,
  "opening_price": 93000000.0,
  "high_price": 96000000.0,
  "low_price": 92000000.0,
  "acc_trade_volume_24h": 123.4,
  "acc_trade_price_24h": 11723000000.0,
  "signed_change_rate": 0.0215,
  "trade_timestamp": 1710000000000
}]
```

변환 로직: 배열[0] 선택, `trade_timestamp` epoch ms → `datetime.fromtimestamp(ts/1000, tz=timezone.utc)`

### 4.2 GET /v1/orderbook — get_orderbook

```
요청: GET https://api.upbit.com/v1/orderbook?markets=KRW-BTC
인증: 불필요
응답: [{
  "market": "KRW-BTC",
  "timestamp": 1710000000000,
  "orderbook_units": [
    {"ask_price": 95100000, "bid_price": 94900000, "ask_size": 0.5, "bid_size": 0.3},
    ...
  ]
}]
```

변환 로직:
- `asks`: `orderbook_units[:depth]`에서 `(ask_price, ask_size)` 추출, 오름차순 정렬
- `bids`: `orderbook_units[:depth]`에서 `(bid_price, bid_size)` 추출, 내림차순 정렬

### 4.3 GET /v1/candles/{path} — get_candles

```
1m:  GET /v1/candles/minutes/1?market=KRW-BTC&count=200
1h:  GET /v1/candles/minutes/60?market=KRW-BTC&count=200
1d:  GET /v1/candles/days?market=KRW-BTC&count=200

응답: [{
  "market": "KRW-BTC",
  "candle_date_time_utc": "2024-03-10T00:00:00",
  "opening_price": 93000000.0,
  "high_price": 96000000.0,
  "low_price": 92000000.0,
  "trade_price": 95000000.0,
  "candle_acc_trade_volume": 123.4,
  ...
}]
```

변환 로직: `candle_date_time_utc` → `datetime.fromisoformat(...).replace(tzinfo=timezone.utc)`. 최신순 반환(Upbit 기본).

### 4.4 POST /v1/orders — place_order

```
# 지정가 매수
POST /v1/orders
Authorization: Bearer {JWT}
Content-Type: application/json
{
  "market": "KRW-BTC",
  "side": "bid",
  "ord_type": "limit",
  "price": "95000000",
  "volume": "0.001"
}

# 시장가 매수 (Order.price = 총 KRW 금액)
{
  "market": "KRW-BTC",
  "side": "bid",
  "ord_type": "price",
  "price": "100000"
}

# 시장가 매도
{
  "market": "KRW-BTC",
  "side": "ask",
  "ord_type": "market",
  "volume": "0.001"
}

응답:
{
  "uuid": "order-uuid",
  "market": "KRW-BTC",
  "side": "bid",
  "ord_type": "limit",
  "state": "wait",
  "volume": "0.001",
  "price": "95000000",
  "executed_volume": "0.0",
  "paid_fee": "0",
  "created_at": "2024-03-10T10:00:00+09:00"
}
```

### 4.5 DELETE /v1/order — cancel_order

```
DELETE https://api.upbit.com/v1/order?uuid={order_id}
Authorization: Bearer {JWT with query_hash}

응답: { "uuid": "...", "state": "cancel", ... }
```

query_hash 생성: `SHA-512("uuid={order_id}")` hex digest

### 4.6 GET /v1/accounts — get_balance

```
GET https://api.upbit.com/v1/accounts
Authorization: Bearer {JWT}

응답: [{
  "currency": "KRW",
  "balance": "10000000.0",
  "locked": "0.0",
  ...
}, {
  "currency": "BTC",
  "balance": "0.1",
  "locked": "0.0",
  ...
}]
```

### 4.7 GET /v1/orders/chance — get_trading_fee

```
GET https://api.upbit.com/v1/orders/chance?market=KRW-BTC
Authorization: Bearer {JWT with query_hash}

응답: {
  "ask_fee": "0.0005",
  "bid_fee": "0.0005",
  "market": { "id": "KRW-BTC", ... },
  ...
}
```

변환: `maker_fee = bid_fee`, `taker_fee = ask_fee` (Upbit은 maker/taker 동일 수수료)

### 4.8 GET /v1/api_keys — verify_api_key (1단계)

```
GET https://api.upbit.com/v1/api_keys
Authorization: Bearer {JWT}

응답: [{
  "access_key": "...",
  "expire_at": "2025-03-10T00:00:00+09:00"
}]
```

---

## 5. 에러 처리 전략

### 5.1 HTTP 상태 코드별 처리

| HTTP 상태 | 처리 방식 |
|----------|----------|
| 200/201 | 정상 응답 |
| 400 | `response.json()["error"]["name"]` → UPBIT_ERROR_MAP 조회 |
| 401 | ExchangeAuthError |
| 403 | ExchangePermissionError |
| 404 | ExchangeOrderError (주문 없음) 또는 ExchangeInvalidSymbolError |
| 418 | ExchangeRateLimitError — Upbit 과도한 요청 시 IP 일시 차단 |
| 429 | ExchangeRateLimitError (Retry-After 헤더 파싱) |
| 5xx | ExchangeUnavailableError (Circuit Breaker 카운트 증가) |
| httpx.TimeoutException | ExchangeNetworkError |
| httpx.ConnectError | ExchangeNetworkError |

### 5.2 Circuit Breaker 연동

`_execute_rest(self._do_request, ...)` 호출 구조에서 5xx 응답은 `ExchangeUnavailableError`를 raise하여 CircuitBreaker의 실패 카운터를 증가시킨다. 인증/권한/심볼 오류(`_EXCLUDED_FROM_CB`)는 Circuit Breaker에 영향 없음.

### 5.3 WebSocket 재연결 전략

```
초기 연결 실패 → 1s 대기 → 재시도
연결 끊김 감지 → Exponential Backoff with jitter
  - 1회: 1s ± 0.1s
  - 2회: 2s ± 0.2s
  - 3회: 4s ± 0.4s
  - ...
  - 최대: min(2^n, 60)s
최대 reconnect_max 회 초과 → ExchangeNetworkError raise (구독 콜백 없음)
재연결 성공 시 → _send_subscription_message() 자동 재구독
```

---

## 6. SymbolMapper 전략 — 정적 Fallback + 동적 갱신

**2단계 전략**: 서버 안정성을 위해 정적 맵을 fallback으로 유지하고, `initialize()` 시 동적 갱신을 시도한다.

### 6.1 정적 Fallback (`constants.py` → `UPBIT_STATIC_MARKETS`)

`types.py`의 `SymbolMapper._MAPS[ExchangeType.UPBIT]`는 초기값으로 `UPBIT_STATIC_MARKETS` 15개를 사용한다.

```python
ExchangeType.UPBIT: {
    "BTC/KRW":  "KRW-BTC",
    "ETH/KRW":  "KRW-ETH",
    "XRP/KRW":  "KRW-XRP",
    "SOL/KRW":  "KRW-SOL",
    "ADA/KRW":  "KRW-ADA",
    "DOGE/KRW": "KRW-DOGE",
    "DOT/KRW":  "KRW-DOT",
    "AVAX/KRW": "KRW-AVAX",
    "MATIC/KRW":"KRW-MATIC",
    "LINK/KRW": "KRW-LINK",
    "ATOM/KRW": "KRW-ATOM",
    "NEAR/KRW": "KRW-NEAR",
    "TRX/KRW":  "KRW-TRX",
    "LTC/KRW":  "KRW-LTC",
    "BCH/KRW":  "KRW-BCH",
}
```

### 6.2 동적 갱신 (`_refresh_symbol_map()`)

`UpbitProvider.initialize()` 시 `GET /v1/market/all` 호출:
- KRW 마켓만 필터링: `"KRW-BTC"` → `"BTC/KRW"` 변환
- `SymbolMapper._MAPS[ExchangeType.UPBIT]` 전체 교체
- `SymbolMapper._REVERSE` 캐시 초기화 (다음 `to_symbol()` 호출 시 재빌드)
- 실패 시: WARNING 로그 + 정적 fallback 유지 (서버 기동 중단 없음)

---

## 7. `__init__.py` 공개 API

```python
# server/app/providers/upbit/__init__.py
"""Upbit 거래소 Provider — BaseExchangeProvider 구현체."""

from .provider import UpbitProvider

__all__ = ["UpbitProvider"]
```

```python
# server/app/providers/__init__.py 추가
from .upbit import UpbitProvider  # noqa: F401 — 임포트 시 자동 Registry 등록
```

---

## 8. 코드 컨벤션 (base_impl.py 패턴 준수)

- 모든 REST 메서드는 반드시 `await self._execute_rest(self._do_{action}, ...)` 래퍼 경유
- `_do_{action}` 내부 메서드: 실제 httpx 호출 + 응답 파싱 담당
- 클래스 상수는 `UPPER_CASE`, 인스턴스 변수는 `_` prefix
- httpx 예외는 `_request()` 헬퍼에서 `ExchangeNetworkError`로 변환
- 타입 힌트: `from __future__ import annotations` + `mypy --strict` 준수
- docstring: Google 스타일
- `from decimal import Decimal` — float 연산 금지, 모든 가격/수량은 Decimal

---

## 9. 구현 순서 (python-backend-expert 참고)

1. **ST1 — 스캐폴딩**: `upbit/__init__.py`, `constants.py` 빈 파일 + `__init__.py` import 추가
2. **ST2 — JWT 인증**: `auth.py` (UpbitJwtAuth) + 단위 테스트
3. **ST3 — REST 구현**: `provider.py` REST 메서드 전체 구현 + 단위 테스트 (httpx mock)
4. **ST4 — WebSocket**: `stream.py` (_UpbitWebSocketClient) + 재연결 테스트
5. **ST5 — 통합**: Provider에 WS 위임 메서드 연결 + SymbolMapper 확장
6. **ST6 — 등록**: `factory.py`에서 UPBIT → UpbitProvider로 교체 + 통합 테스트

---

## 10. JWT 인증 흐름 상세

```
[인증 불필요 API — 시세/호가/캔들/마켓 목록]
  httpx GET → 응답 처리 (Authorization 헤더 없음)

[인증 필요 API — 주문/잔고/수수료/API키]
  1. UpbitJwtAuth.generate(query_params)
     ├─ payload = {access_key: key, nonce: UUID4}
     ├─ query_params 있으면 (GET with params, DELETE):
     │   ├─ query_string = urlencode(params)
     │   ├─ query_hash = SHA-512(query_string).hexdigest()
     │   └─ payload += {query_hash, query_hash_alg: "SHA512"}
     ├─ json_body 있으면 (POST):
     │   ├─ body_string = "key=value&key=value" 변환
     │   ├─ query_hash = SHA-512(body_string).hexdigest()
     │   └─ payload += {query_hash, query_hash_alg: "SHA512"}
     └─ jwt.encode(payload, secret_key, algorithm="HS512")

  2. httpx 요청
     └─ headers = {"Authorization": f"Bearer {token}"}

  3. 에러 시:
     ├─ 401 invalid_access_key → ExchangeAuthError
     ├─ 401 jwt_verification → ExchangeAuthError
     ├─ 401 nonce_used → ExchangeAuthError (nonce 재사용)
     └─ 401 expired_access_key → ExchangeAuthError (90일 만료)
```

**주의사항**:
- Upbit 공식 문서 기준 JWT 서명 알고리즘은 **HS512** (HMAC-SHA512)
- `nonce`는 매 요청마다 고유 UUID를 생성해야 함 (재사용 시 `nonce_used` 에러)
- Secret Key는 Base64 인코딩되어 있지 않으므로 그대로 사용
- POST body의 query_hash는 body를 `key=value&key=value` 형식으로 변환 후 해시

---

## 11. WebSocket 연결 관리 상세

### 11.1 Upbit WS 제약사항

| 항목 | 값 |
|------|------|
| 연결 URL | `wss://api.upbit.com/websocket/v1` |
| 연결 타임아웃 | **120초** 무통신 시 서버 연결 종료 |
| IP당 최대 연결 | 5개 |
| 인증 | ticker/orderbook은 public → 인증 불필요 |
| TLS | 1.2 이상 필수, 1.3 권장 |
| 압축 | RFC 7692 지원 (선택) |

### 11.2 PING 전략

Upbit는 120초 무통신 시 연결을 종료하므로, `EXCHANGE_WS_PING_INTERVAL`(기본 30초) 간격으로 PING을 전송:

```python
async def _ping_loop(self) -> None:
    """주기적 PING 전송 (120초 타임아웃 방지)."""
    while self._ws and not self._ws.closed:
        await asyncio.sleep(self._ping_interval)  # 30초
        try:
            await self._ws.send("PING")
        except Exception:
            break  # 재연결 로직이 처리
```

### 11.3 구독 메시지 형식

```json
[
  {"ticket": "unique-uuid-per-request"},
  {"type": "ticker", "codes": ["KRW-BTC", "KRW-ETH"], "is_only_realtime": true},
  {"type": "orderbook", "codes": ["KRW-BTC"]},
  {"format": "DEFAULT"}
]
```

- `ticket`: 고유 요청 식별자 (UUID4)
- `is_only_realtime`: true 시 스냅샷 없이 실시간 데이터만 수신
- `format`: DEFAULT(풀 필드명) 또는 SIMPLE(축약 필드명)

### 11.4 데이터 수신 및 파싱

Upbit WS 응답은 **바이너리** 또는 **텍스트** JSON:

```python
@staticmethod
def _parse_message(raw: bytes | str) -> dict | None:
    if isinstance(raw, bytes):
        return json.loads(raw.decode("utf-8"))
    return json.loads(raw)
```

수신 데이터의 `type` 필드로 ticker/orderbook 구분 후 해당 콜백 호출.

---

## 12. 테스트 전략

### 12.1 단위 테스트 (CI 포함)

| 테스트 파일 | 대상 | 방법 | 예상 테스트 수 |
|------------|------|------|-------------|
| `test_auth.py` | JWT 토큰 생성 | PyJWT decode 검증, SHA512 해시 검증 | 7 |
| `test_mappers.py` | 데이터 변환 | Upbit 샘플 JSON → 공통 모델 필드 매칭 | 10 |
| `test_provider.py` | REST 메서드 | httpx MockTransport로 HTTP 응답 모킹 | 14 |
| `test_websocket.py` | WS 연결/구독 | websockets 모킹, 재연결 로직 검증 | 7 |

### 12.2 단위 테스트 상세

**test_auth.py** (7건):
- `test_generate_without_query` — access_key, nonce 포함, query_hash 미포함
- `test_generate_with_query_params` — query_hash, query_hash_alg="SHA512" 포함
- `test_generate_for_body` — POST body → query_hash 변환
- `test_query_hash_sha512` — SHA512 해시 정합성
- `test_authorization_header_format` — "Bearer {token}" 형식
- `test_nonce_uniqueness` — 연속 호출 시 nonce 다름
- `test_algorithm_hs512` — JWT 헤더 `alg` = "HS512" 검증

**test_mappers.py** (10건):
- `test_parse_ticker` — REST ticker 변환
- `test_parse_orderbook` — REST orderbook 변환 (asks 오름차순, bids 내림차순)
- `test_parse_orderbook_depth` — depth 파라미터 적용
- `test_parse_candle` — REST candle 변환
- `test_parse_order_result_limit` — 지정가 주문 결과 변환
- `test_parse_order_result_market_buy` — 시장가 매수 결과 (ord_type=price)
- `test_parse_order_result_market_sell` — 시장가 매도 결과 (ord_type=market)
- `test_parse_balance` — 잔고 변환
- `test_ws_ticker_code_field` — WS ticker의 "code" → "market" 매핑
- `test_decimal_precision` — float 미사용, Decimal 정밀도 유지

**test_provider.py** (14건):
- `test_get_ticker` — 정상 시세 조회
- `test_get_orderbook` — 정상 호가 조회
- `test_get_candles_1m` — 1분봉 조회
- `test_get_candles_1d` — 일봉 조회 (경로 분기)
- `test_place_order_limit_buy` — 지정가 매수
- `test_place_order_market_buy` — 시장가 매수 (ord_type=price)
- `test_place_order_market_sell` — 시장가 매도 (ord_type=market)
- `test_cancel_order` — 주문 취소
- `test_get_balance` — 잔고 조회
- `test_get_trading_fee` — 수수료 조회
- `test_verify_api_key_valid` — 유효한 API 키
- `test_error_mapping_auth_401` — 401 → ExchangeAuthError
- `test_error_mapping_insufficient_funds` — insufficient_funds_bid → ExchangeInsufficientBalanceError
- `test_initialize_loads_markets` — initialize() 시 SymbolMapper 등록

**test_websocket.py** (7건):
- `test_connect_disconnect` — 연결/해제
- `test_subscribe_ticker_message_format` — 구독 메시지 JSON 형식
- `test_recv_ticker_callback` — 수신 → mapper → 콜백 호출
- `test_recv_orderbook_callback` — 호가 수신 → 콜백
- `test_reconnect_on_close` — 연결 끊김 시 재연결
- `test_reconnect_exponential_backoff` — 대기 시간 1s, 2s, 4s...
- `test_max_reconnect_attempts` — 최대 재연결 횟수 초과 시 중단

### 12.3 통합 테스트 (로컬 전용, CI 제외)

```python
# @pytest.mark.skipif(not os.getenv("UPBIT_API_KEY"), reason="No Upbit API key")
class TestUpbitIntegration:
    async def test_get_ticker_real(self): ...
    async def test_get_orderbook_real(self): ...
    async def test_verify_api_key_real(self): ...
    async def test_websocket_ticker_stream(self): ...  # 5초 후 disconnect
```

### 12.4 예상 테스트 수량

| 카테고리 | 파일 수 | 테스트 수 |
|---------|--------|----------|
| 단위 테스트 | 4 | 38 |
| 통합 테스트 | 1 | 4 |
| **합계** | **5** | **42** |

---

## 13. 의존성

### 13.1 신규 추가 패키지

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `PyJWT` | >=2.8 | Upbit JWT 토큰 생성 (HS512) |
| `websockets` | >=12.0 | WebSocket 클라이언트 |

### 13.2 기존 활용 패키지 (추가 설치 불필요)

| 패키지 | 용도 |
|--------|------|
| `httpx` | REST HTTP 클라이언트 (BaseExchangeProvider에서 이미 사용) |
| `pydantic` | 공통 데이터 모델 |
| `redis.asyncio` | Rate Limiter |

### 13.3 pyproject.toml 변경

```toml
[project]
dependencies = [
    # ... 기존 의존성 ...
    "PyJWT>=2.8",
    "websockets>=12.0",
]
```

> **참고**: v1-5에서 `python-jose[cryptography]`를 사용 중이나, Upbit JWT는 단순 HS512 서명만 필요하므로 `PyJWT`가 적절. 두 라이브러리의 import 경로가 다르므로 (`jose.jwt` vs `jwt`) 충돌 없음.

---

## 14. Upbit API 제한사항 참조

| 항목 | 제한 |
|------|------|
| REST Rate Limit (Quotation) | 10 req/sec/IP (ticker 그룹 공유) |
| REST Rate Limit (Exchange) | 8 req/sec/API key |
| WebSocket 연결 수 | IP당 최대 5개 |
| WS 타임아웃 | 120초 무통신 시 연결 종료 |
| 최소 주문 금액 | KRW 마켓: 5,000원 |
| API 키 유효기간 | 90일 (연장 가능) |
| HTTP 418 | 과도한 요청 시 IP 일시 차단 |
| TLS 최소 버전 | 1.2 이상 필수 |

---

## 15. 미결 사항

| 항목 | 내용 | 결정 필요자 |
|------|------|-----------|
| 시장가 매수 KRW 예산 | `Order.price` 재사용 vs 별도 필드 | exchange-api-expert / python-backend-expert |
| BTC/USDT 마켓 지원 | KRW 마켓만 vs BTC/USDT 마켓도 포함 | project-architect |
