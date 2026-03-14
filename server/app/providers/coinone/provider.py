"""CoinOne 거래소 REST + WebSocket Provider 구현체."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from ..base_impl import BaseExchangeProvider
from ..circuit_breaker import CircuitBreaker
from ..enums import ApiKeyPermission, ExchangeType, OrderMethod, OrderSide, OrderStatus
from ..exceptions import (
    ExchangeAuthError,
    ExchangeDataError,
    ExchangeNetworkError,
    ExchangeOrderError,
    ExchangePermissionError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from ..factory import ExchangeProviderRegistry
from ..types import (
    ApiKeyInfo,
    Balance,
    Candle,
    Order,
    OrderBook,
    OrderResult,
    Ticker,
    TradingFee,
)
from .auth import CoinOneHmacAuth
from .constants import (
    COINONE_ERROR_MAP,
    COINONE_REST_BASE_URL,
    COINONE_STATIC_MARKETS,
    HTTP_STATUS_ERROR_MAP,
    TIMEFRAME_TO_INTERVAL,
    get_orderbook_size,
)
from .mappers import (
    _parse_currencies,
    parse_balance,
    parse_cancel_result,
    parse_candle,
    parse_get_order_result,
    parse_order_result,
    parse_orderbook,
    parse_ticker,
    parse_trading_fee,
)
from .stream import _CoinOneWebSocketClient

logger = logging.getLogger(__name__)

# ── Rate Limiter (lazy import 방지) ───────────────────────────────────────────

try:
    from app.core.rate_limiter import ExchangeRateLimiter
except ImportError:
    ExchangeRateLimiter = Any  # type: ignore[assignment,misc]


@ExchangeProviderRegistry.register(ExchangeType.COINONE)
class CoinOneProvider(BaseExchangeProvider):
    """CoinOne 거래소 REST + WebSocket 구현체.

    BaseExchangeProvider를 상속하여 Rate Limiter + Circuit Breaker를
    모든 REST 호출에 자동 적용. 모든 REST 호출은 _execute_rest() 경유 필수.

    CoinOne 고유 특성:
    - HMAC-SHA512 인증 (access_token + secret_key)
    - Private API는 모두 POST
    - 에러 응답이 HTTP 200 + result="error" 형식
    - 마켓 코드: target_currency 대문자 (예: "BTC")
    """

    def __init__(
        self,
        exchange_type: ExchangeType,
        api_key: str,       # CoinOne access_token
        api_secret: str,    # CoinOne secret_key
        rate_limiter: Any,
        circuit_breaker: CircuitBreaker,
        user_id: str,
    ) -> None:
        super().__init__(exchange_type, api_key, api_secret, rate_limiter, circuit_breaker, user_id)
        self._auth = CoinOneHmacAuth(api_key, api_secret)
        self._ws: _CoinOneWebSocketClient | None = None

    # ── 초기화 / 정리 ─────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """HTTP 클라이언트 준비 + SymbolMapper 동적 갱신 (fallback 포함).

        1. super().initialize() — httpx 클라이언트 lazy init
        2. GET /public/v2/markets/KRW → SymbolMapper._MAPS[COINONE] 갱신
           실패 시 WARNING 로그 + COINONE_STATIC_MARKETS fallback 유지
        """
        await super().initialize()
        try:
            await self._refresh_symbol_map()
        except ExchangeNetworkError:
            logger.warning(
                "Failed to load CoinOne market list, using static fallback (%d markets)",
                len(COINONE_STATIC_MARKETS),
            )

    async def close(self) -> None:
        """HTTP 클라이언트 + WebSocket 정리."""
        if self._ws is not None:
            await self._ws.disconnect()
            self._ws = None
        await super().close()

    # ── SymbolMapper 동적 갱신 ────────────────────────────────────────────────

    async def _refresh_symbol_map(self) -> None:
        """GET /public/v2/markets/KRW 호출 → SymbolMapper 갱신.

        CoinOne 응답:
        {"result":"success","markets":[{"target_currency":"BTC",...},...]})

        KRW 마켓: target_currency 대문자 그대로 → "{TARGET}/KRW" → "TARGET" (대문자 저장)
        """
        from ..types import SymbolMapper

        raw = await self._request("GET", "/public/v2/markets/KRW", auth=False)
        if not isinstance(raw, dict):
            raise ExchangeDataError("coinone", "Unexpected /public/v2/markets/KRW response format")

        markets = raw.get("markets", [])
        if not isinstance(markets, list):
            raise ExchangeDataError("coinone", "Unexpected markets field format")

        new_map: dict[str, str] = {}
        for item in markets:
            target = item.get("target_currency", "")
            if target:
                target_upper = target.upper()
                new_map[f"{target_upper}/KRW"] = target_upper

        if new_map:
            SymbolMapper._MAPS[ExchangeType.COINONE] = new_map
            SymbolMapper._REVERSE = {}  # 역방향 캐시 초기화
            logger.debug("CoinOne SymbolMapper updated: %d markets", len(new_map))

    # ── HTTP 헬퍼 ─────────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: bool = False,
    ) -> Any:
        """HTTP 요청 실행 + CoinOne 에러 응답 처리.

        Upbit의 _request()와 동일한 시그니처로 Codebase 일관성 유지.

        Args:
            method: "GET" (Public) | "POST" (Private)
            path: API 엔드포인트 경로 e.g. "/public/v2/ticker_new/KRW/btc"
            params: Public GET 쿼리 파라미터
            json_body: Private POST body (auth=True 시 access_token, nonce 자동 삽입)
            auth: True 시 HMAC-SHA512 서명 헤더 추가

        Returns:
            응답 JSON (dict 또는 list)

        Raises:
            ExchangeNetworkError: 연결 오류, 타임아웃
            ExchangeAuthError / ExchangePermissionError / ...: 거래소 에러 응답
        """
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
                method,
                url,
                params=params,
                json=final_body,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise ExchangeNetworkError("coinone", "Request timeout", exc) from exc
        except httpx.ConnectError as exc:
            raise ExchangeNetworkError("coinone", "Connection failed", exc) from exc
        except httpx.HTTPError as exc:
            raise ExchangeNetworkError("coinone", f"HTTP error: {exc}", exc) from exc

        # 응답 파싱
        body_data: Any = {}
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

    def _parse_coinone_error(
        self,
        status_code: int,
        body: Any,
        headers: httpx.Headers | None = None,
    ) -> None:
        """CoinOne 에러 응답을 ExchangeError 계층으로 변환 후 raise.

        CoinOne 에러 형식: {"result": "error", "error_code": "103", "error_msg": "..."}

        파싱 순서:
        1. body["error_code"] → COINONE_ERROR_MAP 직접 매핑
        2. HTTP 상태 코드 → HTTP_STATUS_ERROR_MAP 폴백
        3. 5xx → ExchangeUnavailableError
        4. 기타 → ExchangeDataError

        Args:
            status_code: HTTP 상태 코드
            body: 응답 본문 dict
            headers: 응답 헤더 (Retry-After 파싱용)

        Raises:
            ExchangeRateLimitError: Rate Limit 초과
            ExchangeAuthError: 인증 실패
            ExchangePermissionError: 권한 부족
            ExchangeUnavailableError: 서버 오류
            ExchangeDataError: 기타 오류
        """
        error_code = ""
        error_msg = str(body)

        if isinstance(body, dict):
            error_code = str(body.get("error_code", ""))
            error_msg = body.get("error_msg", str(body))

        # 1. COINONE_ERROR_MAP 직접 매핑
        if error_code in COINONE_ERROR_MAP:
            exc_cls = COINONE_ERROR_MAP[error_code]
            if exc_cls is ExchangeRateLimitError:
                retry_after = self._parse_retry_after(headers)
                raise ExchangeRateLimitError("coinone", retry_after)
            raise exc_cls("coinone", error_msg)

        # 2. HTTP 상태 코드 폴백
        if status_code in HTTP_STATUS_ERROR_MAP:
            exc_cls = HTTP_STATUS_ERROR_MAP[status_code]
            if exc_cls is ExchangeRateLimitError:
                retry_after = self._parse_retry_after(headers)
                raise ExchangeRateLimitError("coinone", retry_after)
            raise exc_cls("coinone", error_msg)

        # 3. 5xx
        if status_code >= 500:
            raise ExchangeUnavailableError("coinone", f"HTTP {status_code}: {error_msg}")

        # 4. 기타
        raise ExchangeDataError("coinone", f"HTTP {status_code}: {error_msg}")

    @staticmethod
    def _parse_retry_after(headers: httpx.Headers | None) -> int | None:
        """Retry-After 헤더에서 초 단위 정수 추출."""
        if headers is None:
            return None
        ra = headers.get("Retry-After")
        if ra is None:
            return None
        try:
            return int(ra)
        except (ValueError, TypeError):
            return None

    # ── REST: 시세 / 호가 / 캔들 ──────────────────────────────────────────────

    async def get_ticker(self, market: str) -> Ticker:
        """현재 시세 조회.

        Args:
            market: CoinOne 마켓 코드 (target_currency 대문자) e.g. "BTC"

        Returns:
            Ticker 모델
        """
        return await self._execute_rest(self._do_get_ticker, market)

    async def _do_get_ticker(self, market: str) -> Ticker:
        """GET /public/v2/ticker_new/KRW/{target} 실행."""
        quote, target = _parse_currencies(market)
        data = await self._request(
            "GET",
            f"/public/v2/ticker_new/{quote}/{target.lower()}",
            auth=False,
        )
        if not isinstance(data, dict):
            raise ExchangeDataError("coinone", "Unexpected ticker response format")
        tickers = data.get("tickers", [])
        if not tickers:
            raise ExchangeDataError("coinone", "Empty ticker response")
        return parse_ticker(tickers[0])

    async def get_orderbook(self, market: str, depth: int = 10) -> OrderBook:
        """호가창 조회.

        Args:
            market: CoinOne 마켓 코드 (target_currency 대문자) e.g. "BTC"
            depth: 조회할 호가 개수 (기본 10, CoinOne 허용: 5/10/15/16)

        Returns:
            OrderBook 모델
        """
        return await self._execute_rest(self._do_get_orderbook, market, depth)

    async def _do_get_orderbook(self, market: str, depth: int) -> OrderBook:
        """GET /public/v2/orderbook/KRW/{target}?size={size} 실행."""
        quote, target = _parse_currencies(market)
        size = get_orderbook_size(depth)
        data = await self._request(
            "GET",
            f"/public/v2/orderbook/{quote}/{target.lower()}",
            params={"size": str(size)},
            auth=False,
        )
        if not isinstance(data, dict):
            raise ExchangeDataError("coinone", "Unexpected orderbook response format")
        return parse_orderbook(data, depth=depth)

    async def get_candles(
        self, market: str, timeframe: str, count: int = 200
    ) -> list[Candle]:
        """OHLCV 캔들 데이터 조회.

        Args:
            market: CoinOne 마켓 코드 (target_currency 대문자) e.g. "BTC"
            timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
            count: 조회할 캔들 개수 (기본 200, 1~500)

        Returns:
            list[Candle]: 최신순 정렬
        """
        return await self._execute_rest(self._do_get_candles, market, timeframe, count)

    async def _do_get_candles(
        self, market: str, timeframe: str, count: int
    ) -> list[Candle]:
        """GET /public/v2/chart/KRW/{target}?interval={}&size={} 실행."""
        interval = TIMEFRAME_TO_INTERVAL.get(timeframe)
        if interval is None:
            raise ExchangeDataError("coinone", f"Unsupported timeframe: {timeframe}")
        quote, target = _parse_currencies(market)
        data = await self._request(
            "GET",
            f"/public/v2/chart/{quote}/{target.lower()}",
            params={"interval": interval, "size": str(count)},
            auth=False,
        )
        if not isinstance(data, dict):
            raise ExchangeDataError("coinone", "Unexpected candles response format")
        chart = data.get("chart", [])
        if not isinstance(chart, list):
            raise ExchangeDataError("coinone", "Unexpected chart field format")
        return [parse_candle(item, target_currency=target, timeframe=timeframe) for item in chart]

    # ── REST: 주문 ────────────────────────────────────────────────────────────

    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행.

        CoinOne 주문 방식 분기:
        - BUY + LIMIT  → side=BUY, type=LIMIT, price, qty
        - SELL + LIMIT → side=SELL, type=LIMIT, price, qty
        - BUY + MARKET → side=BUY, type=MARKET, amount (총 KRW 예산)
        - SELL + MARKET → side=SELL, type=MARKET, qty (코인 수량)

        Raises:
            ExchangeAuthError: API 키 인증 실패
            ExchangePermissionError: TRADE 권한 없음
            ExchangeInsufficientBalanceError: 잔고 부족
            ExchangeOrderError: 최소 주문 금액 미달 등
        """
        return await self._execute_rest(self._do_place_order, order)

    async def _do_place_order(self, order: Order) -> OrderResult:
        """POST /v2.1/order 실행 + CoinOne 주문 방식 분기 처리."""
        quote, target = _parse_currencies(order.market)
        side = "BUY" if order.side == OrderSide.BUY else "SELL"

        body: dict[str, Any] = {
            "side": side,
            "quote_currency": quote,
            "target_currency": target,
        }

        if order.method == OrderMethod.LIMIT:
            if order.price is None:
                raise ExchangeOrderError("coinone", "price is required for LIMIT order")
            body["type"] = "LIMIT"
            body["price"] = str(order.price)
            body["qty"] = str(order.quantity)
        elif order.side == OrderSide.BUY:
            # 시장가 매수: amount = 총 KRW 예산 (Order.price 재사용)
            if order.price is None:
                raise ExchangeOrderError(
                    "coinone",
                    "price (KRW budget) is required for MARKET BUY order",
                )
            body["type"] = "MARKET"
            body["amount"] = str(order.price)
        else:
            # 시장가 매도: qty = 코인 수량
            body["type"] = "MARKET"
            body["qty"] = str(order.quantity)

        data = await self._request("POST", "/v2.1/order", json_body=body, auth=True)
        if not isinstance(data, dict):
            raise ExchangeDataError("coinone", "Unexpected place_order response format")

        # place_order 응답에 target_currency, quote_currency 주입
        data.setdefault("target_currency", target)
        data.setdefault("quote_currency", quote)
        data.setdefault("side", side)
        data.setdefault("type", body.get("type", "LIMIT"))
        if "qty" in body:
            data.setdefault("qty", body["qty"])
        if "price" in body:
            data.setdefault("price", body["price"])

        return parse_order_result(data)

    async def cancel_order(self, market: str, exchange_order_id: str) -> bool:
        """주문 취소.

        Returns:
            True: 취소 성공 또는 이미 체결 완료
            False: 취소 실패
        """
        return await self._execute_rest(self._do_cancel_order, market, exchange_order_id)

    async def get_order(self, market: str, exchange_order_id: str) -> OrderResult:
        """주문 상태 조회.

        POST /v2.1/order/query_orders — 거래소 실시간 동기화용.
        """
        return await self._execute_rest(self._do_get_order, market, exchange_order_id)

    async def _do_get_order(self, market: str, exchange_order_id: str) -> OrderResult:
        """POST /v2.1/order/query_orders 실행."""
        quote, target = _parse_currencies(market)
        body: dict[str, Any] = {
            "order_id": exchange_order_id,
            "quote_currency": quote,
            "target_currency": target,
        }
        data = await self._request("POST", "/v2.1/order/query_orders", json_body=body, auth=True)
        if not isinstance(data, dict):
            raise ExchangeDataError("coinone", "Unexpected get_order response format")

        # 응답에 currency 정보 주입
        data.setdefault("target_currency", target)
        data.setdefault("quote_currency", quote)

        return parse_get_order_result(data)

    async def _do_cancel_order(self, market: str, exchange_order_id: str) -> bool:
        """POST /v2.1/order/cancel 실행."""
        quote, target = _parse_currencies(market)
        body: dict[str, Any] = {
            "order_id": exchange_order_id,
            "quote_currency": quote,
            "target_currency": target,
        }
        data = await self._request("POST", "/v2.1/order/cancel", json_body=body, auth=True)
        if not isinstance(data, dict):
            raise ExchangeDataError("coinone", "Unexpected cancel_order response format")

        # cancel 응답에 target_currency 주입
        data.setdefault("target_currency", target)
        data.setdefault("quote_currency", quote)

        result = parse_cancel_result(data)
        # FILLED, PARTIAL, CANCELLED 모두 취소 처리 완료로 간주
        return result.status in (OrderStatus.CANCELLED, OrderStatus.FILLED, OrderStatus.PARTIAL)

    # ── REST: 잔고 / 수수료 ───────────────────────────────────────────────────

    async def get_balance(self) -> list[Balance]:
        """전체 잔고 조회.

        Returns:
            list[Balance]: 보유 자산 목록
        """
        return await self._execute_rest(self._do_get_balance)

    async def _do_get_balance(self) -> list[Balance]:
        """POST /v2.1/account/balance/all 실행."""
        data = await self._request("POST", "/v2.1/account/balance/all", auth=True)
        if not isinstance(data, dict):
            raise ExchangeDataError("coinone", "Unexpected balance response format")
        balances = data.get("balances", [])
        if not isinstance(balances, list):
            raise ExchangeDataError("coinone", "Unexpected balances field format")
        return [parse_balance(item) for item in balances]

    async def get_trading_fee(self, market: str) -> TradingFee:
        """수수료 조회.

        POST /v2.1/account/trade_fee/{quote}/{target} → maker_fee, taker_fee 추출.

        Args:
            market: CoinOne 마켓 코드 (target_currency 대문자) e.g. "BTC"

        Returns:
            TradingFee 모델
        """
        return await self._execute_rest(self._do_get_trading_fee, market)

    async def _do_get_trading_fee(self, market: str) -> TradingFee:
        """POST /v2.1/account/trade_fee/{quote}/{target} 실행."""
        quote, target = _parse_currencies(market)
        data = await self._request(
            "POST",
            f"/v2.1/account/trade_fee/{quote}/{target}",
            auth=True,  # body=None → access_token+nonce만 포함
        )
        if not isinstance(data, dict):
            raise ExchangeDataError("coinone", "Unexpected trading_fee response format")
        return parse_trading_fee(data, market=market)

    # ── REST: API 키 검증 ─────────────────────────────────────────────────────

    async def verify_api_key(self) -> ApiKeyInfo:
        """API 키 유효성 및 권한 2단계 검증.

        1. POST /v2.1/account/balance/all → is_valid 결정 + VIEW_BALANCE 권한
        2. POST /v2.1/account/trade_fee/KRW/BTC → VIEW_ORDERS + TRADE 권한

        Returns:
            ApiKeyInfo: is_valid, permissions, error_message
        """
        return await self._execute_rest(self._do_verify_api_key)

    async def _do_verify_api_key(self) -> ApiKeyInfo:
        """2단계 API 키 권한 검증 실행."""
        permissions: list[ApiKeyPermission] = []

        # 1단계: 잔고 조회로 API 키 유효성 + VIEW_BALANCE 확인
        try:
            await self._request("POST", "/v2.1/account/balance/all", auth=True)
            permissions.append(ApiKeyPermission.VIEW_BALANCE)
            permissions.append(ApiKeyPermission.TRADE)  # 잔고 조회 가능 = 거래 가능
        except (ExchangeAuthError, ExchangePermissionError) as exc:
            return ApiKeyInfo(
                exchange=ExchangeType.COINONE,
                permissions=[],
                is_valid=False,
                error_message=str(exc),
                has_withdraw_permission=False,
            )
        except ExchangeNetworkError:
            raise

        # 2단계: 수수료 조회로 VIEW_ORDERS 확인
        try:
            await self._request(
                "POST",
                "/v2.1/account/trade_fee/KRW/BTC",
                auth=True,
            )
            permissions.append(ApiKeyPermission.VIEW_ORDERS)
        except (
            ExchangeAuthError,
            ExchangePermissionError,
            ExchangeNetworkError,
            ExchangeRateLimitError,
        ):
            pass

        return ApiKeyInfo(
            exchange=ExchangeType.COINONE,
            permissions=permissions,
            is_valid=True,
            has_withdraw_permission=False,  # v1 범위 밖
        )

    # ── WebSocket ─────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """WebSocket 연결 상태."""
        if self._ws is None:
            return False
        return self._ws.is_connected

    async def connect(self) -> None:
        """WebSocket 연결 수립.

        Raises:
            ExchangeNetworkError: 연결 실패 (최대 재연결 횟수 초과)
        """
        if self._ws is None:
            from app.core.config import settings

            self._ws = _CoinOneWebSocketClient(
                reconnect_max=settings.EXCHANGE_WS_RECONNECT_MAX,
                ping_interval=float(settings.EXCHANGE_WS_PING_INTERVAL),
            )
        await self._ws.connect()
        self._ws_connected = True

    async def disconnect(self) -> None:
        """WebSocket 연결 종료."""
        if self._ws is not None:
            await self._ws.disconnect()
        self._ws_connected = False

    async def subscribe_ticker(
        self,
        markets: list[str],
        callback: Callable[[Ticker], Awaitable[None]],
    ) -> None:
        """실시간 시세 구독.

        Args:
            markets: CoinOne 마켓 코드 목록 (target_currency 대문자) e.g. ["BTC", "ETH"]
            callback: 시세 수신 시 호출할 async 콜백
        """
        if self._ws is None:
            await self.connect()
        await self._ws.subscribe("TICKER", markets, callback)  # type: ignore[union-attr]

    async def subscribe_orderbook(
        self,
        markets: list[str],
        callback: Callable[[OrderBook], Awaitable[None]],
    ) -> None:
        """실시간 호가창 구독."""
        if self._ws is None:
            await self.connect()
        await self._ws.subscribe("ORDERBOOK", markets, callback)  # type: ignore[union-attr]

    async def unsubscribe(self, markets: list[str] | None = None) -> None:
        """구독 해제.

        Args:
            markets: 해제할 마켓 목록. None 시 전체 해제.
        """
        if self._ws is not None:
            await self._ws.unsubscribe(markets)
