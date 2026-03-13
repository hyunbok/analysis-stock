# v1-10 CoinOne 거래소 프로바이더 구현 — 설계서

> **작성**: project-architect (시스템 아키텍처/흐름/구현계획), code-architect (코드 구조/API 규격/인터페이스 설계)
> **대상 태스크**: v1-10 — CoinOne REST API + WebSocket 구현, HMAC-SHA512 인증, 실시간 시세/호가 수신
> **현재 상태**: 구현 완료 (2026-03-13) — 44/44 테스트 통과, 코드 리뷰 LGTM

---

## 1. 개요

v1-8에서 구축한 거래소 추상화 계층(BaseExchangeProvider, ExchangeProviderRegistry) 위에 CoinOne 거래소 구체 구현체를 작성한다. v1-9 Upbit Provider와 동일한 패턴을 따르되, CoinOne 고유의 HMAC-SHA512 인증 방식과 API 규격을 반영한다.

**의존성**: v1-8 (Exchange Abstraction Layer) 완료, v1-9 (Upbit Provider) 참조.

**구현 범위**:
- CoinOne REST API 8개 메서드 (get_ticker, get_orderbook, get_candles, place_order, cancel_order, get_balance, get_trading_fee, verify_api_key)
- CoinOne WebSocket 2개 채널 (ticker, orderbook), 자동 재연결
- HMAC-SHA512 인증 (access_token + secret_key, Base64 payload + signature 헤더)
- CoinOne 에러 코드(숫자) → ExchangeError 계층 매핑

**Upbit과의 주요 차이점**:
| 항목 | Upbit | CoinOne |
|------|-------|---------|
| 인증 방식 | JWT HS512 (Bearer 토큰) | HMAC-SHA512 (Payload + Signature 헤더) |
| Private API HTTP | GET/POST/DELETE 혼합 | 모두 POST |
| 마켓 코드 | `KRW-BTC` 단일 문자열 | `quote_currency`/`target_currency` 분리 |
| 에러 형식 | `{"error":{"name":"...","message":"..."}}` | `{"result":"error","error_code":"4","error_msg":"..."}` |
| WS URL | `wss://api.upbit.com/websocket/v1` | `wss://stream.coinone.co.kr` |
| WS 구독 형식 | JSON 배열 `[{ticket},{type,codes}]` | `{request_type, channel, topic}` 개별 메시지 |
| WS 타임아웃 | 120초 | 30분 |

---

## 2. 파일/모듈 구조

### 2.1 신규 파일 목록

```
server/app/providers/coinone/
├── __init__.py        # CoinOneProvider 공개 노출
├── auth.py            # CoinOneHmacAuth (HMAC-SHA512 서명 생성 유틸리티)
├── constants.py       # URL, 타임프레임 매핑, CoinOne 에러 코드 매핑, 정적 마켓 목록(fallback)
├── mappers.py         # CoinOne API 응답 → 공통 모델 변환 순수함수 (상태 없음)
├── provider.py        # CoinOneProvider (BaseExchangeProvider 상속, 핵심 구현)
└── stream.py          # _CoinOneWebSocketClient (WS 연결 관리, provider.py가 컴포지션으로 사용)
```

> **HMAC-SHA512 인증**: JWT가 아닌 HMAC 서명 방식. `hashlib` + `hmac` 표준 라이브러리만 사용하므로 추가 패키지 불필요.
>
> **`stream.py` 명칭**: Upbit과 동일하게 `ExchangeStreamProvider` ABC와 명칭 일관성 유지.
>
> **`mappers.py` 분리**: CoinOne 응답 필드명이 Upbit과 완전히 다르므로 독립 모듈 필수. 모든 함수는 순수함수 `parse_ticker(data: dict) -> Ticker` 형태.

### 2.2 기존 파일 수정

| 파일 | 수정 내용 |
|------|----------|
| `server/app/providers/__init__.py` | `from .coinone import CoinOneProvider` 추가 (자동 등록 트리거) |
| `server/app/providers/types.py` | `SymbolMapper._MAPS[ExchangeType.COINONE]` — 주요 마켓 심볼 확장 (15개) |

### 2.3 클래스 계층도

```
ExchangeProvider (ABC)
└── BaseExchangeProvider (Rate Limiter + Circuit Breaker 주입)
    ├── UpbitProvider                         ← v1-9 구현 완료
    └── CoinOneProvider                      ← 신규 구현체
            ├── _auth: CoinOneHmacAuth       ← 컴포지션 (HMAC-SHA512 서명)
            └── _ws: _CoinOneWebSocketClient  ← 컴포지션 (WS 연결/구독)
```

---

## 3. 모듈 상세 설계

### 3.1 `auth.py` — CoinOneHmacAuth

```python
import base64
import hashlib
import hmac
import json
import uuid
from typing import Any


class CoinOneHmacAuth:
    """CoinOne HMAC-SHA512 인증 헤더 생성기.

    CoinOne 인증 방식:
    - 공개 API (시세/호가/캔들): 인증 불필요 (GET)
    - 비공개 API (주문/잔고): POST + HMAC 헤더 필수
    - 서명 절차:
      1. 요청 body dict에 access_token, nonce(UUID4) 삽입
      2. JSON 직렬화 → Base64 인코딩 → X-COINONE-PAYLOAD 헤더
      3. HMAC-SHA512(payload_base64, secret_key) → hex digest → X-COINONE-SIGNATURE 헤더
    """

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key       # CoinOne access_token
        self._api_secret = api_secret.encode()  # hmac은 bytes 필요

    def sign(self, body: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
        """body에 인증 필드 추가 → (signed_body, auth_headers) 반환.

        단일 메서드로 body와 headers를 함께 반환하는 이유:
        CoinOne은 POST body == payload 원본이므로 body도 함께 돌려줘야
        _request()에서 json=signed_body로 전달 가능.

        Args:
            body: 요청 파라미터 dict (access_token, nonce 제외).
                  None 시 access_token + nonce만 포함된 body 생성.

        Returns:
            (signed_body, headers) 튜플:
            - signed_body: access_token + nonce 포함된 최종 body (원본 dict 변경 없음)
            - headers: X-COINONE-PAYLOAD + X-COINONE-SIGNATURE

        Implementation:
            # ⚠️ 원본 dict mutation 방지: spread 연산자로 복사
            signed_body = {
                "access_token": self._api_key,
                "nonce": str(uuid.uuid4()),
                **(body or {}),  # 원본 복사 — 호출자의 dict 변경하지 않음
            }
            payload_bytes = json.dumps(signed_body).encode()
            payload_b64 = base64.b64encode(payload_bytes).decode()
            signature = hmac.new(
                self._api_secret,
                payload_b64.encode(),
                hashlib.sha512,
            ).hexdigest()
            headers = {
                "X-COINONE-PAYLOAD": payload_b64,
                "X-COINONE-SIGNATURE": signature,
            }
            return signed_body, headers
        """
```

> **Upbit과의 차이**: Upbit은 JWT 라이브러리(PyJWT)로 토큰 생성, CoinOne은 표준 `hmac`+`hashlib`+`base64`만 사용. 추가 의존성 없음.
> **단일 메서드 설계**: Upbit `UpbitJwtAuth`는 `generate()`, `generate_for_body()`, `authorization_header()` 3개 메서드가 필요했으나, CoinOne은 모든 Private API가 POST이므로 `sign(body)` 단일 메서드로 충분.
> **access_token**: Upbit의 api_key에 해당. CoinOne은 body에 access_token을 포함시키는 방식.
> **nonce**: UUID v4 형식 (Upbit과 동일). 매 요청마다 고유 값 필수.

### 3.2 `constants.py` — 상수 및 매핑

```python
# REST / WebSocket URL
COINONE_REST_BASE_URL: str = "https://api.coinone.co.kr"
COINONE_WS_URL: str = "wss://stream.coinone.co.kr"

# 타임프레임 → CoinOne chart interval 매핑
# CoinOne은 interval 파라미터를 직접 사용
TIMEFRAME_TO_INTERVAL: dict[str, str] = {
    "1m":  "1m",
    "3m":  "3m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1d",
    "1w":  "1w",
    "1M":  "1mon",
}

# CoinOne 에러 코드(숫자) → ExchangeError 서브클래스 매핑
# CoinOne 에러 응답 형식: {"result": "error", "error_code": "4", "error_msg": "..."}
COINONE_ERROR_MAP: dict[str, type[ExchangeError]] = {
    # 인증/권한 에러
    "4":   ExchangeRateLimitError,        # Blocked user access (rate limit 초과 시 반환)
    # ⚠️ error_code "4"는 계정 블록에도 사용될 수 있음.
    # exchange-api-expert가 실제 테스트 후 ExchangeAuthError 전환 필요 시 조정.
    "11":  ExchangeAuthError,              # Access token is missing
    "12":  ExchangeAuthError,              # Invalid access token
    "23":  ExchangeAuthError,              # Invalid App Secret
    "40":  ExchangePermissionError,        # Invalid API permission
    "50":  ExchangeAuthError,              # KYC authentication required
    "53":  ExchangeAuthError,              # Two Factor Auth Fail
    # Payload/Signature 에러
    "120": ExchangeAuthError,              # V2 API payload is missing
    "121": ExchangeAuthError,              # V2 API signature is missing
    "122": ExchangeAuthError,              # V2 API nonce is missing
    "123": ExchangeAuthError,              # V2 API signature is not correct
    "130": ExchangeAuthError,              # Nonce must be positive integer
    "131": ExchangeAuthError,              # Nonce must be bigger than last nonce
    "132": ExchangeAuthError,              # Nonce already used
    "133": ExchangeAuthError,              # Nonce must be UUID format
    # 주문/잔고 에러
    "101": ExchangeOrderError,             # Invalid format
    "103": ExchangeInsufficientBalanceError, # Lack of Balance
    "104": ExchangeOrderError,             # Order id does not exist
    "105": ExchangeOrderError,             # Price is not correct
    "107": ExchangeOrderError,             # Parameter error
    "108": ExchangeInvalidSymbolError,     # Unknown cryptocurrency
    "109": ExchangeInvalidSymbolError,     # Unknown cryptocurrency pair
    "111": ExchangeOrderError,             # Price difference too large
    "113": ExchangeOrderError,             # Quantity is too low
    "114": ExchangeOrderError,             # Invalid order amount
    "115": ExchangeOrderError,             # Maximum quantity exceeded
    "116": ExchangeOrderError,             # Already traded
    "117": ExchangeOrderError,             # Already canceled
    # 가격 제한 에러
    "300": ExchangeOrderError,             # Invalid order information
    "301": ExchangeOrderError,             # Sell below base price
    "302": ExchangeOrderError,             # Sell above base price
    "303": ExchangeOrderError,             # Buy below base price
    "304": ExchangeOrderError,             # Buy above base price
    "305": ExchangeOrderError,             # Invalid quantity
    "306": ExchangeOrderError,             # Below minimum amount
    "307": ExchangeOrderError,             # Exceeds maximum amount
    # 서버 에러
    "405": ExchangeUnavailableError,       # Server error
}

# HTTP 상태 코드 기반 폴백 매핑 (error_code 매칭 실패 시)
HTTP_STATUS_ERROR_MAP: dict[int, type[ExchangeError]] = {
    401: ExchangeAuthError,
    403: ExchangePermissionError,
    429: ExchangeRateLimitError,
}

# CoinOne 수수료율 기본값
COINONE_DEFAULT_MAKER_FEE: Decimal = Decimal("0.0002")  # 0.02% (API 기본 수수료)
COINONE_DEFAULT_TAKER_FEE: Decimal = Decimal("0.0002")  # 0.02%

# 정적 마켓 목록 (initialize() 동적 로드 실패 시 fallback)
# CoinOne SymbolMapper 값: target_currency 대문자 문자열 (API 응답 기준)
COINONE_STATIC_MARKETS: dict[str, str] = {
    "BTC/KRW":   "BTC",
    "ETH/KRW":   "ETH",
    "XRP/KRW":   "XRP",
    "SOL/KRW":   "SOL",
    "ADA/KRW":   "ADA",
    "DOGE/KRW":  "DOGE",
    "DOT/KRW":   "DOT",
    "AVAX/KRW":  "AVAX",
    "MATIC/KRW": "MATIC",
    "LINK/KRW":  "LINK",
    "ATOM/KRW":  "ATOM",
    "NEAR/KRW":  "NEAR",
    "TRX/KRW":   "TRX",
    "LTC/KRW":   "LTC",
    "BCH/KRW":   "BCH",
}
```

> **마켓 코드 설계**: CoinOne API 응답의 `target_currency`는 대문자(`"BTC"`)를 사용한다. SymbolMapper에는 대문자를 저장하고, REST URL path에 사용할 때 `.lower()`로 변환한다. quote_currency는 항상 `"KRW"`로 고정 (v1 범위에서 KRW 마켓만 지원).

### 3.3 `mappers.py` — 응답 변환 순수함수

```python
"""CoinOne API 응답 dict → 공통 Pydantic 모델 변환 순수함수 모음.

모든 함수:
- 상태(state)를 갖지 않음 (순수함수)
- 입력: CoinOne API 응답 dict
- 출력: providers/types.py의 공통 모델
- 파싱 실패 시: ExchangeDataError raise
"""

QUOTE_CURRENCY = "KRW"  # v1 범위에서 KRW 마켓 고정

def _to_symbol(quote: str, target: str) -> str:
    """CoinOne API 응답 (quote, target) → 정규화 심볼.
    ("KRW", "BTC") → "BTC/KRW"
    """
    return f"{target.upper()}/{quote.upper()}"

def _parse_currencies(market: str) -> tuple[str, str]:
    """내부 심볼 'BTC/KRW' → (quote_currency='KRW', target_currency='BTC').

    provider._request() 호출 시 path param 및 body 구성에 사용.
    mappers.py에 배치하여 provider.py와 양쪽에서 import 가능 (순환 import 방지).
    """
    target, quote = market.split("/")
    return quote, target

def parse_ticker(data: dict) -> Ticker:
    """CoinOne REST /public/v2/ticker_new 또는 WS TICKER 응답 → Ticker 변환.

    CoinOne REST 필드 매핑:
      last              → price (현재가)
      first             → open_price (시가)
      high              → high_price (고가)
      low               → low_price (저가)
      target_volume     → volume (거래량, target currency)
      quote_volume      → trade_value (거래대금, KRW)
      (last - first) / first → change_rate (계산 필요, 아래 방어 코드 참조)
      timestamp (ms)    → timestamp (UTC datetime)
      target_currency   → market

    change_rate 계산 방어 코드 (first=0 엣지케이스):
      change_rate = (last - first) / first if first != Decimal("0") else Decimal("0")

    CoinOne WS 필드 매핑 (DEFAULT format):
      last              → price
      first             → open_price
      high              → high_price
      low               → low_price
      target_volume     → volume
      quote_volume      → trade_value
      target_currency   → market
      timestamp         → timestamp
    """

def parse_orderbook(data: dict, depth: int = 10) -> OrderBook:
    """CoinOne REST /public/v2/orderbook 또는 WS ORDERBOOK 응답 → OrderBook 변환.

    asks[]: {price, qty} → asks (오름차순)
    bids[]: {price, qty} → bids (내림차순)
    """

def parse_candle(data: dict, target_currency: str, timeframe: str) -> Candle:
    """CoinOne REST /public/v2/chart 단일 캔들 dict → Candle 변환.

    CoinOne 필드 매핑:
      open               → open
      high               → high
      low                → low
      close              → close
      target_volume      → volume
      timestamp (ms)     → timestamp (UTC datetime)
    """

def parse_order_result(data: dict) -> OrderResult:
    """CoinOne REST /v2.1/order POST 또는 /v2.1/order/cancel 응답 → OrderResult 변환.

    CoinOne place_order 응답 필드:
      order_id           → exchange_order_id
      side (BUY/SELL)    → side
      type (LIMIT/MARKET)→ method
      qty                → quantity
      price              → price

    CoinOne cancel_order 응답 필드:
      order_id           → exchange_order_id
      side               → side
      qty, remain_qty, traded_qty → quantity/executed_quantity 계산
      fee                → fee
      fee_rate           → (참조용)
      avg_price          → avg_executed_price
      canceled_at (ms)   → created_at
      ordered_at (ms)    → (참조용)
    """

def parse_balance(data: dict) -> Balance:
    """CoinOne REST /v2.1/account/balance/all 단일 잔고 dict → Balance 변환.

    CoinOne 필드 매핑:
      currency          → currency (대문자 변환)
      available         → available
      limit             → locked (CoinOne은 "limit" 명칭 사용)
    """

def parse_cancel_result(data: dict) -> OrderResult:
    """CoinOne REST /v2.1/order/cancel 응답 전용 파서.

    place_order 응답은 order_id만 반환하지만, cancel 응답은 상세 정보 포함.
    주문 상태 추론:
    - remain_qty == "0" and traded_qty > "0" → FILLED (이미 체결 완료)
    - remain_qty > "0" and traded_qty > "0" → PARTIAL (부분 체결 후 취소)
    - remain_qty > "0" and traded_qty == "0" → CANCELLED (미체결 취소)

    CoinOne 필드 매핑:
      order_id           → exchange_order_id
      side               → side
      qty, remain_qty, traded_qty, canceled_qty → quantity/executed_quantity/status
      fee                → fee
      avg_price          → avg_executed_price
      canceled_at (ms)   → created_at
    """

def parse_trading_fee(data: dict, market: str) -> TradingFee:
    """CoinOne REST /v2.1/account/trade_fee 응답 → TradingFee 변환.

    CoinOne 필드 매핑:
      maker_fee         → maker_fee
      taker_fee         → taker_fee
    """
```

### 3.4 `provider.py` — CoinOneProvider

#### 클래스 시그니처 및 __init__

```python
@ExchangeProviderRegistry.register(ExchangeType.COINONE)
class CoinOneProvider(BaseExchangeProvider):
    """CoinOne 거래소 REST + WebSocket 구현체.

    BaseExchangeProvider를 상속하여 Rate Limiter + Circuit Breaker를
    모든 REST 호출에 자동 적용. 모든 REST 호출은 _execute_rest() 경유 필수.
    """

    def __init__(
        self,
        exchange_type: ExchangeType,
        api_key: str,       # CoinOne access_token
        api_secret: str,    # CoinOne secret_key
        rate_limiter: ExchangeRateLimiter,
        circuit_breaker: CircuitBreaker,
        user_id: str,
    ) -> None:
        super().__init__(exchange_type, api_key, api_secret, rate_limiter, circuit_breaker, user_id)
        self._auth = CoinOneHmacAuth(api_key, api_secret)
        self._ws: _CoinOneWebSocketClient | None = None

    async def initialize(self) -> None:
        """HTTP 클라이언트 준비 + SymbolMapper 동적 갱신 (fallback 포함).

        1. super().initialize() — httpx 클라이언트 lazy init
        2. GET /public/v2/markets/KRW → SymbolMapper._MAPS[COINONE] 갱신
           실패 시 WARNING 로그 + COINONE_STATIC_MARKETS fallback 유지
        """

    async def _refresh_symbol_map(self) -> None:
        """GET /public/v2/markets/KRW 호출 → SymbolMapper 갱신.

        CoinOne 응답: {"result":"success","markets":[{"target_currency":"BTC",...},...]})
        KRW 마켓: target_currency 대문자 그대로 → "{TARGET}/KRW" → "TARGET" (대문자 저장)
        """
```

#### REST 메서드 — CoinOne API 엔드포인트 매핑

| 메서드 | HTTP | CoinOne 엔드포인트 | 인증 | 비고 |
|--------|------|-------------------|------|------|
| `get_ticker(market)` | GET | `/public/v2/ticker_new/KRW/{target}` | 불필요 | tickers 배열[0] 사용 |
| `get_orderbook(market, depth)` | GET | `/public/v2/orderbook/KRW/{target}?size={depth}` | 불필요 | size: 5/10/15/16 |
| `get_candles(market, timeframe, count)` | GET | `/public/v2/chart/KRW/{target}?interval={}&size={}` | 불필요 | interval 매핑 |
| `place_order(order)` | POST | `/v2.1/order` | 필요 | side=BUY/SELL, type=LIMIT/MARKET |
| `cancel_order(market, order_id)` | POST | `/v2.1/order/cancel` | 필요 | order_id + quote/target |
| `get_balance()` | POST | `/v2.1/account/balance/all` | 필요 | balances 배열 |
| `get_trading_fee(market)` | POST | `/v2.1/account/trade_fee/{quote}/{target}` | 필요 | maker_fee, taker_fee |
| `verify_api_key()` | POST | `/v2.1/account/balance/all` | 필요 | 2단계 권한 검증 |

#### place_order 주문 방식 분기

CoinOne의 주문 필드 매핑:

| Order.side | Order.method | CoinOne side | CoinOne type | CoinOne price 필드 | CoinOne qty/amount 필드 |
|------------|--------------|-------------|-------------|-------------------|----------------------|
| BUY | LIMIT | `BUY` | `LIMIT` | `price` | `qty` |
| SELL | LIMIT | `SELL` | `LIMIT` | `price` | `qty` |
| BUY | MARKET | `BUY` | `MARKET` | 없음 | `amount` (총 KRW 예산) |
| SELL | MARKET | `SELL` | `MARKET` | 없음 | `qty` (코인 수량) |

> **주의**: CoinOne 시장가 매수(BUY + MARKET)는 `amount` 필드로 총 KRW 금액을 받는다.
> Upbit과 동일한 패턴: `Order.price` 필드를 KRW 예산으로 재사용. 서비스 레이어에서 이 컨벤션 문서화 필요.

#### verify_api_key 2단계 검증

```
1. POST /v2.1/account/balance/all → 성공 시 is_valid=True + VIEW_BALANCE 권한
   실패(error_code=11/12/40) 시 is_valid=False 반환
2. POST /v2.1/account/trade_fee → 성공 시 VIEW_ORDERS 권한
   실패 시 VIEW_ORDERS 권한 없음
3. TRADE 권한: CoinOne은 TRADE 전용 검증 엔드포인트가 없음.
   VIEW_BALANCE 확인 시 TRADE 자동 부여 — CoinOne API 키 설정에서
   잔고 조회와 거래 권한이 통상적으로 함께 부여되며, 별도 분리 검증 API 미지원.
4. has_withdraw_permission: CoinOne API로 출금 권한 확인 가능하나 v1 범위 밖 → False
```

#### REST 헬퍼 메서드

```python
async def _request(
    self,
    method: str,      # "GET" | "POST"
    path: str,        # "/public/v2/ticker_new/KRW/btc" 등
    *,
    params: dict[str, str] | None = None,   # GET query params
    json_body: dict[str, Any] | None = None, # POST body (인증 필드 제외)
    auth: bool = False,                      # HMAC 헤더 필요 여부
) -> Any:
    """HTTP 요청 실행 + CoinOne 에러 응답 처리.

    Upbit의 _request()와 동일한 시그니처로 Codebase 일관성 유지.

    Args:
        method: "GET" (Public) | "POST" (Private)
        path: API 엔드포인트 경로
        params: Public GET 쿼리 파라미터
        json_body: Private POST body (auth=True 시 access_token, nonce 자동 삽입)
        auth: True 시 HMAC-SHA512 서명 헤더 추가

    Implementation:
        client = await self._get_http_client()
        url = COINONE_REST_BASE_URL + path
        headers: dict[str, str] = {"Content-Type": "application/json"}
        final_body: dict[str, Any] | None = None

        if auth:
            # json_body가 None이면 빈 dict로 서명 (잔고 전체 조회 등)
            signed_body, auth_headers = self._auth.sign(json_body or {})
            headers.update(auth_headers)
            final_body = signed_body
        else:
            final_body = json_body

        try:
            response = await client.request(
                method, url,
                params=params,
                json=final_body,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise ExchangeNetworkError("coinone", ...) from exc
        except httpx.ConnectError as exc:
            raise ExchangeNetworkError("coinone", ...) from exc

        # 응답 파싱
        body_data: dict = {}
        try:
            body_data = response.json()
        except Exception:
            pass

        # 1. HTTP 상태 코드 에러
        if response.status_code not in (200, 201):
            self._parse_coinone_error(response.status_code, body_data, response.headers)

        # 2. ⚠️ CoinOne 고유: HTTP 200 + result="error" 패턴
        #    Upbit과 달리 CoinOne은 HTTP 200으로 에러를 반환하는 경우가 있음
        if isinstance(body_data, dict) and body_data.get("result") == "error":
            self._parse_coinone_error(response.status_code, body_data, response.headers)

        return body_data
    """

def _parse_coinone_error(
    self,
    status_code: int,
    body: dict,
    headers: httpx.Headers | None = None,
) -> None:
    """CoinOne 에러 응답을 ExchangeError 계층으로 변환 후 raise.

    CoinOne 에러 형식: {"result": "error", "error_code": "103", "error_msg": "..."}

    파싱 순서:
    1. body["error_code"] → COINONE_ERROR_MAP 직접 매핑
    2. HTTP 상태 코드 → HTTP_STATUS_ERROR_MAP 폴백
    3. 5xx → ExchangeUnavailableError
    4. 기타 → ExchangeDataError
    """
```

> **Upbit과의 일관성**: `_request(method, path, auth=bool)` 시그니처를 유지하여 Codebase 전체 패턴 통일. code-architect 피드백 반영.
> **HTTP 200 에러 주의**: CoinOne은 HTTP 200 상태 코드로 에러를 반환하는 경우가 있으므로, `result=="error"` 체크를 반드시 수행해야 한다. 이는 Upbit에는 없는 CoinOne 고유 특성.

#### HTTP 상태 코드 기반 폴백 매핑

```python
HTTP_STATUS_ERROR_MAP: dict[int, type[ExchangeError]] = {
    401: ExchangeAuthError,
    403: ExchangePermissionError,
    429: ExchangeRateLimitError,
}
```

### 3.5 `stream.py` — _CoinOneWebSocketClient

#### 클래스 구조

```python
class _CoinOneWebSocketClient:
    """CoinOne WebSocket 단일 연결 + 다중 채널 구독 관리.

    CoinOne WS 특성:
    - SUBSCRIBE/UNSUBSCRIBE/PING 개별 메시지 방식 (Upbit의 배열 방식과 다름)
    - 채널별 구독: TICKER, ORDERBOOK, TRADE
    - topic: {quote_currency, target_currency} 딕셔너리
    - 인증 불필요 (public 데이터)
    - 30분 idle timeout (Upbit 120초 대비 느슨)
    - IP당 최대 20 연결 (Upbit 5개 대비 여유)
    - DEFAULT/SHORT format 지원

    재연결 전략:
    - Exponential Backoff with jitter (Upbit과 동일)
    - 초기 1s → 2s → 4s → 8s → max 60s
    - 최대 reconnect_max 회 시도
    """

    WS_URL = "wss://stream.coinone.co.kr"

    def __init__(self, reconnect_max: int = 5, ping_interval: float = 300.0) -> None:
        """
        Args:
            ping_interval: PING 전송 간격 (초).
                CoinOne은 30분 타임아웃 → 5분(300초) 간격 PING 충분.
                Upbit(30초)보다 여유로운 설정.
        """
        self._ws: Any | None = None
        self._subscriptions: dict[str, dict[str, Any]] = {}  # channel → {markets, callback}
        self._listen_task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        self._reconnect_max = reconnect_max
        self._ping_interval = ping_interval
        self._connected = False

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def subscribe(
        self,
        channel: str,      # "TICKER" | "ORDERBOOK"
        markets: list[str], # target_currency 목록 e.g. ["BTC", "ETH"]
        callback: Callable,
    ) -> None:
        """구독 등록 + 즉시 개별 SUBSCRIBE 메시지 전송.

        CoinOne WS 구독 메시지 (마켓별 개별 전송):
        {
            "request_type": "SUBSCRIBE",
            "channel": "TICKER",
            "topic": {"quote_currency": "KRW", "target_currency": "BTC"}
        }

        ⚠️ 주의: CoinOne WS 문서에 camelCase 포맷 예시도 존재
        (requestType, priceCurrency, productCurrency 등).
        snake_case vs camelCase 및 body 중첩 래퍼 유무는
        exchange-api-expert가 ST10 시작 전 실제 WS 연결로 검증 필수.
        """

    async def unsubscribe(self, markets: list[str] | None = None) -> None:
        """구독 해제 — 개별 UNSUBSCRIBE 메시지 전송."""

    @property
    def is_connected(self) -> bool: ...

    # 내부 메서드
    async def _connect_once(self) -> None: ...
    async def _connect_with_retry(self) -> None: ...

    async def _send_subscribe_messages(self) -> None:
        """현재 _subscriptions 기반으로 개별 SUBSCRIBE 메시지 전송.

        CoinOne은 Upbit과 달리 마켓별로 개별 SUBSCRIBE 메시지를 전송해야 한다.
        """

    async def _ping_loop(self) -> None:
        """주기적 PING 전송 (30분 타임아웃 방지).

        CoinOne PING 메시지:
        {"request_type": "PING"}

        5분(300초) 간격 전송 — 30분 타임아웃 대비 충분한 여유.
        """

    async def _listen_loop(self) -> None: ...

    async def _handle_message(self, raw: str | bytes) -> None:
        """수신 메시지 파싱 → channel 필드 기반 분기 → mappers.py 함수 호출 → 콜백 실행.

        CoinOne WS 응답:
        {"response_type": "DATA", "channel": "TICKER", "data": {...}}
        {"response_type": "DATA", "channel": "ORDERBOOK", "data": {...}}
        {"response_type": "PONG"}  → 무시
        {"response_type": "ERROR", "error_code": ..., "message": ...}  → 로그

        channel="TICKER"    → mappers.parse_ticker(data) → ticker 콜백
        channel="ORDERBOOK" → mappers.parse_orderbook(data) → orderbook 콜백
        channel 미매칭      → 로그 경고 후 무시
        """

    @staticmethod
    def _decode_message(raw: bytes | str) -> dict:
        """텍스트 JSON → dict 변환 (CoinOne WS는 텍스트 JSON만 사용)."""
```

#### WS 메시지 파싱 — CoinOne 응답 필드 매핑

**Ticker 응답 (`channel: "TICKER"`):**

| CoinOne 필드 | 공통 Ticker 필드 | 비고 |
|-------------|----------------|------|
| `target_currency` | `market` | e.g. "BTC" (대문자 유지) |
| `last` | `price` | 현재가 |
| `first` | `open_price` | 당일 시가 (UTC 기준) |
| `high` | `high_price` | 당일 고가 |
| `low` | `low_price` | 당일 저가 |
| `target_volume` | `volume` | 24h 거래량 (코인) |
| `quote_volume` | `trade_value` | 24h 거래대금 (KRW) |
| `(last-first)/first` | `change_rate` | 변동률 계산 (CoinOne 미제공) |
| `timestamp` | `timestamp` | epoch ms → UTC datetime |

**Orderbook 응답 (`channel: "ORDERBOOK"`):**

| CoinOne 필드 | 공통 OrderBook 필드 | 비고 |
|-------------|-------------------|------|
| `target_currency` | `market` | |
| `asks[].price` | `asks[].price` | |
| `asks[].qty` | `asks[].quantity` | |
| `bids[].price` | `bids[].price` | |
| `bids[].qty` | `bids[].quantity` | |
| `timestamp` | `timestamp` | epoch ms |

---

## 4. API 엔드포인트 상세 매핑

### 4.1 GET /public/v2/ticker_new/KRW/{target} — get_ticker

```
요청: GET https://api.coinone.co.kr/public/v2/ticker_new/KRW/btc
인증: 불필요
응답: {
  "result": "success",
  "error_code": "0",
  "server_time": 1710000000000,
  "tickers": [{
    "quote_currency": "KRW",
    "target_currency": "BTC",
    "timestamp": 1710000000000,
    "high": "96000000",
    "low": "92000000",
    "first": "93000000",
    "last": "95000000",
    "quote_volume": "11723000000",
    "target_volume": "123.4",
    "best_asks": [{"price": "95100000", "qty": "0.5"}],
    "best_bids": [{"price": "94900000", "qty": "0.3"}],
    "id": "1710000000000001"
  }]
}
```

변환 로직: `tickers[0]` 선택, `timestamp` epoch ms → datetime. `change_rate`는 `(last - first) / first` 계산 (first=0 시 Decimal("0") 반환).

### 4.2 GET /public/v2/orderbook/KRW/{target} — get_orderbook

```
요청: GET https://api.coinone.co.kr/public/v2/orderbook/KRW/btc?size=10
인증: 불필요
응답: {
  "result": "success",
  "error_code": "0",
  "timestamp": 1710000000000,
  "id": "1710000000000001",
  "quote_currency": "KRW",
  "target_currency": "BTC",
  "asks": [
    {"price": "95100000", "qty": "0.5"},
    {"price": "95200000", "qty": "1.0"}
  ],
  "bids": [
    {"price": "94900000", "qty": "0.3"},
    {"price": "94800000", "qty": "0.7"}
  ]
}
```

변환 로직: `asks` 오름차순, `bids` 내림차순 정렬.

**depth → size 변환 규칙** (CoinOne은 5/10/15/16만 허용):
```python
# constants.py
_ORDERBOOK_VALID_SIZES: tuple[int, ...] = (5, 10, 15, 16)

def get_orderbook_size(depth: int) -> int:
    """depth를 CoinOne 허용 size 중 가장 가까운 값으로 매핑.
    depth <= 5  → 5
    depth <= 10 → 10
    depth <= 15 → 15
    depth > 15  → 16
    """
    for s in _ORDERBOOK_VALID_SIZES:
        if depth <= s:
            return s
    return 16
```

### 4.3 GET /public/v2/chart/KRW/{target} — get_candles

```
요청: GET https://api.coinone.co.kr/public/v2/chart/KRW/btc?interval=1h&size=200
인증: 불필요
응답: {
  "result": "success",
  "error_code": "0",
  "chart": [
    {
      "timestamp": 1710000000000,
      "open": "93000000",
      "high": "96000000",
      "low": "92000000",
      "close": "95000000",
      "target_volume": "123.4",
      "quote_volume": "11723000000"
    }
  ]
}
```

변환 로직: `TIMEFRAME_TO_INTERVAL` 매핑으로 interval 변환. `size` 1~500 (기본 200).

### 4.4 POST /v2.1/order — place_order

```
# 지정가 매수
POST https://api.coinone.co.kr/v2.1/order
X-COINONE-PAYLOAD: {base64 encoded}
X-COINONE-SIGNATURE: {hmac-sha512 hex}
Content-Type: application/json

{
  "access_token": "...",
  "nonce": "uuid-v4",
  "side": "BUY",
  "quote_currency": "KRW",
  "target_currency": "BTC",
  "type": "LIMIT",
  "price": "95000000",
  "qty": "0.001",
  "post_only": false
}

# 시장가 매수 (amount = 총 KRW)
{
  "access_token": "...",
  "nonce": "uuid-v4",
  "side": "BUY",
  "quote_currency": "KRW",
  "target_currency": "BTC",
  "type": "MARKET",
  "amount": "100000"
}

# 시장가 매도
{
  "access_token": "...",
  "nonce": "uuid-v4",
  "side": "SELL",
  "quote_currency": "KRW",
  "target_currency": "BTC",
  "type": "MARKET",
  "qty": "0.001"
}

응답: {
  "result": "success",
  "error_code": "0",
  "order_id": "uuid-value"
}
```

### 4.5 POST /v2.1/order/cancel — cancel_order

```
POST https://api.coinone.co.kr/v2.1/order/cancel
X-COINONE-PAYLOAD: {base64 encoded}
X-COINONE-SIGNATURE: {hmac-sha512 hex}

{
  "access_token": "...",
  "nonce": "uuid-v4",
  "order_id": "uuid-value",
  "quote_currency": "KRW",
  "target_currency": "BTC"
}

응답: {
  "result": "success",
  "error_code": "0",
  "order_id": "uuid-value",
  "price": "95000000",
  "qty": "0.001",
  "remain_qty": "0.001",
  "side": "BUY",
  "traded_qty": "0",
  "canceled_qty": "0.001",
  "fee": "0",
  "fee_rate": "0.0002",
  "avg_price": "0",
  "canceled_at": 1710000000000,
  "ordered_at": 1709999000000
}
```

### 4.6 POST /v2.1/account/balance/all — get_balance

```
POST https://api.coinone.co.kr/v2.1/account/balance/all
X-COINONE-PAYLOAD: {base64 encoded}
X-COINONE-SIGNATURE: {hmac-sha512 hex}

{
  "access_token": "...",
  "nonce": "uuid-v4"
}

응답: {
  "result": "success",
  "error_code": "0",
  "balances": [
    {"currency": "KRW", "available": "10000000", "limit": "0", "average_price": "0"},
    {"currency": "BTC", "available": "0.1", "limit": "0.01", "average_price": "95000000"}
  ]
}
```

변환: `available` → available, `limit` → locked, `currency` → currency (대문자 유지).

### 4.7 POST /v2.1/account/trade_fee/{quote}/{target} — get_trading_fee

```
POST https://api.coinone.co.kr/v2.1/account/trade_fee/KRW/BTC
X-COINONE-PAYLOAD: {base64 encoded}
X-COINONE-SIGNATURE: {hmac-sha512 hex}

{
  "access_token": "...",
  "nonce": "uuid-v4"
}

응답: {
  "result": "success",
  "error_code": "0",
  "maker_fee": "0.0002",
  "taker_fee": "0.0002"
}
```

> **path param + POST 조합**: currencies는 URL path에 위치하지만 HTTP 메서드는 POST.
> body에는 access_token + nonce만 포함되며, `_request("POST", path, auth=True)` 호출 시 `json_body=None`을 전달한다 (auth에서 access_token/nonce 자동 삽입).
> ```python
> async def _do_get_trading_fee(self, market: str) -> TradingFee:
>     quote, target = _parse_currencies(market)
>     data = await self._request(
>         "POST",
>         f"/v2.1/account/trade_fee/{quote}/{target}",
>         auth=True,  # body=None → access_token+nonce만 포함
>     )
> ```

### 4.8 verify_api_key — 2단계 검증

```
1. POST /v2.1/account/balance/all
   → 성공: is_valid=True, VIEW_BALANCE 권한 추가
   → 실패(error_code=11/12/40): is_valid=False 반환

2. POST /v2.1/account/trade_fee/KRW/BTC
   → 성공: VIEW_ORDERS + TRADE 권한 추가
   → 실패: 해당 권한 없음

3. has_withdraw_permission: False (v1 범위 밖)
```

---

## 5. HMAC-SHA512 인증 흐름 상세

```
[인증 불필요 API — 시세/호가/캔들/마켓 목록]
  httpx GET → 응답 처리 (인증 헤더 없음)

[인증 필요 API — 주문/잔고/수수료]
  1. CoinOneHmacAuth.sign(body) → (signed_body, headers)
     ├─ signed_body = {"access_token": key, "nonce": UUID4, **body}  # 원본 mutation 방지
     ├─ payload_bytes = json.dumps(signed_body).encode()
     ├─ payload_b64 = base64.b64encode(payload_bytes).decode()
     ├─ signature = hmac.new(secret_key, payload_b64.encode(), hashlib.sha512).hexdigest()
     └─ headers = {
            "X-COINONE-PAYLOAD": payload_b64,
            "X-COINONE-SIGNATURE": signature,
        }

  2. httpx POST
     └─ headers = 위 헤더, body = signed_body (access_token/nonce 포함)

  3. 에러 시:
     ├─ error_code=11 → ExchangeAuthError (access token missing)
     ├─ error_code=12 → ExchangeAuthError (invalid token)
     ├─ error_code=123 → ExchangeAuthError (signature incorrect)
     ├─ error_code=132 → ExchangeAuthError (nonce reused)
     └─ error_code=40 → ExchangePermissionError (API permission)
```

**Upbit JWT 대비 차이점**:
- Upbit: `jwt.encode(payload, secret, alg="HS512")` → `Authorization: Bearer {token}` 단일 헤더
- CoinOne: `base64(json(body))` → `hmac(payload, secret, SHA512)` → 2개 헤더(PAYLOAD, SIGNATURE) + body에 access_token 포함
- CoinOne은 query_hash 개념 없음 (body 자체가 payload에 포함)
- CoinOne은 PyJWT 의존성 불필요 (표준 라이브러리만 사용)

---

## 6. 에러 처리 전략

### 6.1 에러 응답 파싱

CoinOne은 HTTP 상태 코드가 아닌 **응답 body의 `error_code` 필드**로 에러를 전달한다:

```json
{
  "result": "error",
  "error_code": "103",
  "error_msg": "Lack of Balance"
}
```

**파싱 절차**:
1. HTTP 상태 코드 확인: 2xx가 아닌 경우 네트워크/서버 에러
2. `result` 필드 확인: `"error"`인 경우 `error_code` 추출
3. `COINONE_ERROR_MAP[error_code]` 조회 → 매핑된 예외 raise
4. 미매핑 코드: `ExchangeDataError`로 폴백

### 6.2 Rate Limit 처리

| API 타입 | 제한 | 기준 | 잔여 헤더 |
|---------|------|------|----------|
| Public v2 | 1200/분 | IP | `Public-Ratelimit-Remaining` |
| Private v2.1 Order | 40/초 | 포트폴리오 | `Private-Order-Ratelimit-Remaining` |
| Private v2.1 기타 | 80/초 | 포트폴리오 | `Private-Ratelimit-Remaining` |

CoinOne Rate Limit 초과 시 `error_code: "4"` (Blocked user access)를 반환.
`ExchangeRateLimiter`(Redis Token Bucket)가 클라이언트 측에서 선제 차단하므로, 서버 측 Rate Limit은 안전망 역할.

### 6.3 Circuit Breaker 연동

기존 `BaseExchangeProvider._execute_rest()` → `CircuitBreaker.call()` 체인 100% 재사용.
`error_code: "405"` (Server error)는 `ExchangeUnavailableError`로 매핑 → Circuit Breaker 실패 카운트 증가.
인증/권한/심볼/잔고 에러(`_EXCLUDED_FROM_CB`)는 Circuit Breaker에 영향 없음.

### 6.4 WebSocket 재연결 전략

Upbit과 동일한 Exponential Backoff with jitter:
```
초기 연결 실패 → 1s 대기 → 재시도
연결 끊김 감지 → Exponential Backoff with jitter
  - 1회: 1s ± 0.1s
  - 2회: 2s ± 0.2s
  - 3회: 4s ± 0.4s
  - ...
  - 최대: min(2^n, 60)s
최대 reconnect_max 회 초과 → ExchangeNetworkError raise
재연결 성공 시 → _send_subscribe_messages() 자동 재구독
```

---

## 7. SymbolMapper 전략

### 7.1 마켓 코드 설계

CoinOne은 Upbit(`KRW-BTC`)과 달리 `quote_currency`/`target_currency`를 분리한다.
SymbolMapper에는 `target_currency` 대문자를 마켓 코드로 저장 (API 응답 기준):

```python
# 정규화 심볼 → 마켓 코드 (target_currency 대문자)
"BTC/KRW" → "BTC"
"ETH/KRW" → "ETH"
```

Provider 내부에서 API 호출 시 `_parse_currencies()` 헬퍼 사용:
```python
# mappers._parse_currencies("BTC") → ("KRW", "BTC")
quote, target = _parse_currencies(market)

# get_ticker: target → URL 경로에 소문자로 변환하여 사용 (API 요구사항)
f"/public/v2/ticker_new/{quote}/{target.lower()}"  # SymbolMapper 저장은 대문자, URL만 lower()

# place_order: body에 분리
body = {"quote_currency": quote, "target_currency": target}
```

### 7.2 동적 갱신

`CoinOneProvider.initialize()` 시 `GET /public/v2/markets/KRW` 호출:
- 응답에서 `target_currency` 추출
- `SymbolMapper._MAPS[ExchangeType.COINONE]` 갱신
- 실패 시: WARNING + `COINONE_STATIC_MARKETS` fallback 유지

---

## 8. `__init__.py` 공개 API

```python
# server/app/providers/coinone/__init__.py
"""CoinOne 거래소 Provider — BaseExchangeProvider 구현체."""

from .provider import CoinOneProvider

__all__ = ["CoinOneProvider"]
```

```python
# server/app/providers/__init__.py 추가
from .coinone import CoinOneProvider  # noqa: F401 — 임포트 시 자동 Registry 등록
```

---

## 9. 코드 컨벤션 (Upbit Provider 패턴 준수)

- 모든 REST 메서드는 반드시 `await self._execute_rest(self._do_{action}, ...)` 래퍼 경유
- `_do_{action}` 내부 메서드: 실제 httpx 호출 + 응답 파싱 담당
- `_request(method, path, auth=bool)` 단일 헬퍼: Upbit과 동일 시그니처로 Codebase 일관성 유지
- HTTP 200 + `result="error"` 체크 반드시 수행 (CoinOne 고유 특성)
- 클래스 상수는 `UPPER_CASE`, 인스턴스 변수는 `_` prefix
- httpx 예외는 `_request()` 내부에서 `ExchangeNetworkError`로 변환
- 타입 힌트: `from __future__ import annotations` + `mypy --strict` 준수
- docstring: Google 스타일
- `from decimal import Decimal` — float 연산 금지, 모든 가격/수량은 Decimal

---

## 10. WebSocket 연결 관리 상세

### 10.1 CoinOne WS 제약사항

| 항목 | 값 |
|------|------|
| 연결 URL | `wss://stream.coinone.co.kr` |
| 유휴 타임아웃 | **30분** 무통신 시 서버 연결 종료 |
| IP당 최대 연결 | 20개 |
| 인증 | ticker/orderbook은 public → 인증 불필요 |
| 메시지 형식 | JSON 텍스트 (바이너리 미사용) |
| 필드명 케이스 | 대문자 (SUBSCRIBE, TICKER, ORDERBOOK) |

### 10.2 PING 전략

CoinOne은 30분 타임아웃으로 Upbit(120초) 대비 여유롭다. 5분(300초) 간격 PING 전송:

```python
async def _ping_loop(self) -> None:
    """주기적 PING 전송 (30분 타임아웃 방지)."""
    while self._ws and not getattr(self._ws, "closed", True):
        await asyncio.sleep(self._ping_interval)  # 300초
        try:
            await self._ws.send(json.dumps({"request_type": "PING"}))
        except Exception:
            break  # 재연결 로직이 처리
```

### 10.3 구독 메시지 형식

```json
// 개별 구독 (마켓별로 개별 전송)
{"request_type": "SUBSCRIBE", "channel": "TICKER", "topic": {"quote_currency": "KRW", "target_currency": "BTC"}}
{"request_type": "SUBSCRIBE", "channel": "TICKER", "topic": {"quote_currency": "KRW", "target_currency": "ETH"}}

// 구독 해제
{"request_type": "UNSUBSCRIBE", "channel": "TICKER", "topic": {"quote_currency": "KRW", "target_currency": "BTC"}}
```

> **Upbit과의 차이**: Upbit은 단일 JSON 배열로 모든 마켓을 한번에 구독. CoinOne은 마켓별 개별 SUBSCRIBE 메시지.

### 10.4 수신 메시지 형식

```json
// 연결 성공
{"response_type": "CONNECTED", "data": {"session_id": "uuid"}}

// 데이터 수신
{"response_type": "DATA", "channel": "TICKER", "data": {
  "quote_currency": "KRW",
  "target_currency": "BTC",
  "timestamp": 1710000000000,
  "last": "95000000",
  "first": "93000000",
  "high": "96000000",
  "low": "92000000",
  "target_volume": "123.4",
  "quote_volume": "11723000000"
}}

// PONG 응답
{"response_type": "PONG"}

// 에러
{"response_type": "ERROR", "error_code": 4290, "message": "Too many connections"}
```

### 10.5 WS 에러 코드

| 코드 | 의미 | 처리 |
|------|------|------|
| 4290 | IP 연결 수 초과 (>20) | 자동 해제, 재연결 중단 |
| 기타 | 일반 에러 | 로그 + 재연결 시도 |

---

## 11. 구현 순서 (서브태스크 매핑)

| ST | 담당 | 내용 | 의존 |
|----|------|------|------|
| ST1 | exchange-api-expert | 스캐폴딩 + HMAC-SHA512 인증 (`auth.py`, `constants.py`, `__init__.py`) | - |
| ST2 | exchange-api-expert | get_ticker, get_orderbook (`_public_request`, `mappers.py` ticker/orderbook) | ST1 |
| ST3 | exchange-api-expert | get_candles + Redis 캐싱 | ST2 |
| ST4 | exchange-api-expert | verify_api_key, get_trading_fee (`_private_request`) | ST1 |
| ST5 | exchange-api-expert | place_order, cancel_order (주문 방식 분기) | ST4 |
| ST6 | exchange-api-expert | get_balance | ST4 |
| ST7 | python-backend-expert | Rate Limiting 통합 — **기존 인프라 100% 재사용, 별도 구현 없음** | ST1 |
| ST8 | python-backend-expert | Circuit Breaker 통합 — **기존 인프라 100% 재사용, 별도 구현 없음** | ST1 |
| ST9 | exchange-api-expert | 에러 처리 및 예외 매핑 (`_parse_coinone_error`, `COINONE_ERROR_MAP`) | ST2, ST4 |
| ST10 | exchange-api-expert | WebSocket 실시간 시세 구독 (`stream.py`) | ST2 |

> **ST7, ST8**: `BaseExchangeProvider._execute_rest()`가 Rate Limiter와 Circuit Breaker를 자동 적용하므로, CoinOneProvider에서 별도 구현 없이 `_execute_rest()` 경유만 하면 된다. 이 서브태스크는 정합성 확인 + 테스트만 수행.

---

## 12. 테스트 전략

### 12.1 단위 테스트 (CI 포함)

| 테스트 파일 | 대상 | 방법 | 예상 테스트 수 |
|------------|------|------|-------------|
| `test_auth.py` | HMAC-SHA512 서명 | base64/hmac 결과 검증, nonce 포함 확인 | 6 |
| `test_mappers.py` | 데이터 변환 | CoinOne 샘플 JSON → 공통 모델 필드 매칭 | 10 |
| `test_provider.py` | REST 메서드 | httpx MockTransport로 HTTP 응답 모킹 | 15 |
| `test_websocket.py` | WS 연결/구독 | websockets 모킹, 재연결 로직 검증 | 7 |

### 12.2 단위 테스트 상세

**test_auth.py** (6건):
- `test_sign_payload_base64` — body → JSON → base64 인코딩 정합성
- `test_sign_hmac_sha512` — HMAC-SHA512 서명 검증 (알려진 입력 → 기대 출력)
- `test_sign_includes_access_token` — body에 access_token 자동 삽입
- `test_sign_includes_uuid_nonce` — nonce가 UUID v4 형식
- `test_nonce_uniqueness` — 연속 호출 시 nonce 다름
- `test_signed_headers_format` — X-COINONE-PAYLOAD, X-COINONE-SIGNATURE 헤더 존재

**test_mappers.py** (10건):
- `test_parse_ticker` — REST ticker 변환
- `test_parse_ticker_change_rate` — change_rate 계산 (last-first)/first + first=0 방어
- `test_parse_orderbook` — REST orderbook 변환 (asks 오름차순, bids 내림차순)
- `test_parse_orderbook_depth` — depth 파라미터 적용
- `test_parse_candle` — REST candle 변환
- `test_parse_order_result` — 주문 결과 변환
- `test_parse_cancel_result` — 취소 결과 변환
- `test_parse_balance` — 잔고 변환 (limit → locked)
- `test_parse_trading_fee` — 수수료 변환
- `test_decimal_precision` — float 미사용, Decimal 정밀도 유지

**test_provider.py** (15건):
- `test_get_ticker` — 정상 시세 조회
- `test_get_orderbook` — 정상 호가 조회
- `test_get_candles_1h` — 1시간봉 조회
- `test_get_candles_1d` — 일봉 조회
- `test_place_order_limit_buy` — 지정가 매수
- `test_place_order_limit_sell` — 지정가 매도
- `test_place_order_market_buy` — 시장가 매수 (amount 사용)
- `test_place_order_market_sell` — 시장가 매도 (qty 사용)
- `test_cancel_order` — 주문 취소
- `test_get_balance` — 잔고 조회
- `test_get_trading_fee` — 수수료 조회
- `test_verify_api_key_valid` — 유효한 API 키
- `test_verify_api_key_invalid` — 유효하지 않은 API 키
- `test_error_mapping_auth` — error_code 12 → ExchangeAuthError
- `test_error_mapping_insufficient_balance` — error_code 103 → ExchangeInsufficientBalanceError

**test_websocket.py** (7건):
- `test_connect_disconnect` — 연결/해제
- `test_subscribe_ticker_message_format` — 개별 SUBSCRIBE 메시지 형식
- `test_recv_ticker_callback` — TICKER 수신 → mapper → 콜백 호출
- `test_recv_orderbook_callback` — ORDERBOOK 수신 → 콜백
- `test_reconnect_on_close` — 연결 끊김 시 재연결
- `test_reconnect_exponential_backoff` — 대기 시간 1s, 2s, 4s...
- `test_ping_message_format` — PING 메시지 JSON 형식

### 12.3 통합 테스트 (로컬 전용, CI 제외)

```python
# @pytest.mark.skipif(not os.getenv("COINONE_ACCESS_TOKEN"), reason="No CoinOne API key")
class TestCoinOneIntegration:
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

**없음** — CoinOne HMAC-SHA512 인증은 Python 표준 라이브러리(`hmac`, `hashlib`, `base64`, `json`, `uuid`)만 사용.

### 13.2 기존 활용 패키지 (추가 설치 불필요)

| 패키지 | 용도 |
|--------|------|
| `httpx` | REST HTTP 클라이언트 (BaseExchangeProvider에서 이미 사용) |
| `websockets` | WebSocket 클라이언트 (v1-9에서 이미 추가) |
| `pydantic` | 공통 데이터 모델 |
| `redis.asyncio` | Rate Limiter |

> **Upbit과의 차이**: Upbit은 `PyJWT>=2.8`이 필요했으나, CoinOne은 추가 패키지 없이 구현 가능. `websockets`는 v1-9에서 이미 설치됨.

---

## 14. CoinOne API 제한사항 참조

| 항목 | 제한 |
|------|------|
| REST Rate Limit (Public v2) | 1200 req/min/IP |
| REST Rate Limit (Private v2.1 Order) | 40 req/sec/포트폴리오 |
| REST Rate Limit (Private v2.1 기타) | 80 req/sec/포트폴리오 |
| WebSocket 연결 수 | IP당 최대 20개 |
| WS 타임아웃 | 30분 무통신 시 연결 종료 |
| Orderbook 기본 크기 | 15 (5/10/15/16 선택) |
| Chart 최대 크기 | 500개 캔들 |
| Nonce 형식 (v2.1) | UUID v4 |
| 수수료율 (API 사용자) | Maker 0.02% / Taker 0.02% |

---

## 15. 미결 사항

| 항목 | 내용 | 결정 필요자 |
|------|------|-----------|
| WS ORDERBOOK vs ORDERBOOK_V2 | CoinOne은 ORDERBOOK_V2 채널도 제공 — 구현 시 exchange-api-expert가 두 채널 비교 후 선택 (ORDERBOOK_V2 권장) | exchange-api-expert |
| XRP/USDT 마켓 지원 | CoinOne은 KRW 외 USDT 마켓도 지원 → v1 범위 밖 | project-architect |
| post_only 파라미터 | 지정가 주문 시 post_only 기본값 (false 권장) | exchange-api-expert |
| limit_price 파라미터 | 시장가 주문의 가격 상한/하한 보호 | exchange-api-expert |
| stop_limit 주문 지원 | CoinOne은 STOP_LIMIT 지원 → v1 범위 밖 | project-architect |
| COINONE_ERROR_MAP 보완 | 현재 주요 에러 코드만 매핑 — 구현 시 실제 테스트를 통해 누락 코드 보완 필요 | exchange-api-expert |
