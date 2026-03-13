"""Upbit 거래소 REST + WebSocket Provider 구현체."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import httpx

from ..base_impl import BaseExchangeProvider
from ..circuit_breaker import CircuitBreaker
from ..enums import ApiKeyPermission, ExchangeType, OrderMethod, OrderSide
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
from .auth import UpbitJwtAuth
from .constants import (
    HTTP_STATUS_ERROR_MAP,
    TIMEFRAME_TO_CANDLE_PATH,
    UPBIT_ERROR_MAP,
    UPBIT_REST_BASE_URL,
    UPBIT_STATIC_MARKETS,
)
from .mappers import (
    parse_balance,
    parse_candle,
    parse_order_result,
    parse_orderbook,
    parse_ticker,
)
from .stream import _UpbitWebSocketClient

logger = logging.getLogger(__name__)

# ── Rate Limiter (lazy import 방지) ───────────────────────────────────────────

try:
    from app.core.rate_limiter import ExchangeRateLimiter
except ImportError:
    ExchangeRateLimiter = Any  # type: ignore[assignment,misc]


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
        rate_limiter: Any,
        circuit_breaker: CircuitBreaker,
        user_id: str,
    ) -> None:
        super().__init__(exchange_type, api_key, api_secret, rate_limiter, circuit_breaker, user_id)
        self._auth = UpbitJwtAuth(api_key, api_secret)
        self._ws: _UpbitWebSocketClient | None = None

    # ── 초기화 / 정리 ─────────────────────────────────────────────────────────

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

    async def close(self) -> None:
        """HTTP 클라이언트 + WebSocket 정리."""
        if self._ws is not None:
            await self._ws.disconnect()
            self._ws = None
        await super().close()

    # ── SymbolMapper 동적 갱신 ────────────────────────────────────────────────

    async def _refresh_symbol_map(self) -> None:
        """GET /v1/market/all 호출 → SymbolMapper 갱신.

        Upbit 응답: [{"market": "KRW-BTC", "korean_name": "비트코인", ...}, ...]
        KRW 마켓만 필터링: "KRW-{BASE}" → "{BASE}/KRW"
        """
        from ..types import SymbolMapper

        raw = await self._request("GET", "/v1/market/all", auth=False)
        if not isinstance(raw, list):
            raise ExchangeDataError("upbit", "Unexpected /v1/market/all response format")

        new_map: dict[str, str] = {}
        for item in raw:
            market = item.get("market", "")
            if market.startswith("KRW-"):
                base = market[4:]  # "KRW-BTC" → "BTC"
                new_map[f"{base}/KRW"] = market

        if new_map:
            SymbolMapper._MAPS[ExchangeType.UPBIT] = new_map
            SymbolMapper._REVERSE = {}  # 역방향 캐시 초기화
            logger.debug("Upbit SymbolMapper updated: %d markets", len(new_map))

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
        """HTTP 요청 실행 + Upbit 에러 응답 처리.

        Args:
            method: "GET" | "POST" | "DELETE"
            path: "/v1/ticker" 등 (앞에 "/" 포함)
            params: query string 파라미터
            json_body: POST body (JSON)
            auth: JWT 헤더 필요 여부

        Returns:
            응답 JSON (dict 또는 list)

        Raises:
            ExchangeNetworkError: 연결 오류, 타임아웃
            ExchangeAuthError / ExchangePermissionError / ...: 거래소 에러 응답
        """
        client = await self._get_http_client()
        url = UPBIT_REST_BASE_URL + path
        headers: dict[str, str] = {}

        if auth:
            if json_body is not None:
                token = self._auth.generate_for_body(
                    {k: str(v) for k, v in json_body.items()}
                )
                headers = {"Authorization": f"Bearer {token}"}
            elif params:
                headers = self._auth.authorization_header(query_params=params)
            else:
                headers = self._auth.authorization_header()

        try:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise ExchangeNetworkError("upbit", "Request timeout", exc) from exc
        except httpx.ConnectError as exc:
            raise ExchangeNetworkError("upbit", "Connection failed", exc) from exc
        except httpx.HTTPError as exc:
            raise ExchangeNetworkError("upbit", f"HTTP error: {exc}", exc) from exc

        if response.status_code not in (200, 201):
            body: dict = {}
            try:
                body = response.json()
            except Exception:
                pass
            self._parse_upbit_error(response.status_code, body, response.headers)

        return response.json()

    def _parse_upbit_error(
        self,
        status_code: int,
        body: dict,
        headers: httpx.Headers | None = None,
    ) -> None:
        """Upbit 에러 응답을 ExchangeError 계층으로 변환 후 raise.

        Args:
            status_code: HTTP 상태 코드
            body: 응답 본문 dict
            headers: 응답 헤더 (Retry-After 파싱용)

        Raises:
            ExchangeRateLimitError: 429/418 응답
            ExchangeAuthError: 401 인증 실패
            ExchangePermissionError: 403 권한 부족
            ExchangeUnavailableError: 5xx 서버 오류
            ExchangeDataError: 기타 파싱 실패
        """
        # Upbit 에러 형식: { "error": { "name": "...", "message": "..." } }
        error_obj = body.get("error", {}) if isinstance(body, dict) else {}
        error_name = error_obj.get("name", "") if isinstance(error_obj, dict) else ""
        error_msg = (
            error_obj.get("message", str(body))
            if isinstance(error_obj, dict)
            else str(body)
        )

        # 1. UPBIT_ERROR_MAP 직접 매핑
        if error_name in UPBIT_ERROR_MAP:
            exc_cls = UPBIT_ERROR_MAP[error_name]
            if exc_cls is ExchangeRateLimitError:
                retry_after = self._parse_retry_after(headers)
                raise ExchangeRateLimitError("upbit", retry_after)
            raise exc_cls("upbit", error_msg)

        # 2. 429/418 — Retry-After 파싱
        if status_code in (429, 418):
            retry_after = self._parse_retry_after(headers)
            raise ExchangeRateLimitError("upbit", retry_after)

        # 3. HTTP 상태 코드 폴백
        if status_code in HTTP_STATUS_ERROR_MAP:
            exc_cls = HTTP_STATUS_ERROR_MAP[status_code]
            raise exc_cls("upbit", error_msg)

        # 4. 5xx
        if status_code >= 500:
            raise ExchangeUnavailableError("upbit", f"HTTP {status_code}: {error_msg}")

        # 5. 기타
        raise ExchangeDataError("upbit", f"HTTP {status_code}: {error_msg}")

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

    # ── REST: 시세 / 호가 / 캔들 (exchange-api-expert ST3 담당) ─────────────

    async def get_ticker(self, market: str) -> Ticker:
        """현재 시세 조회.

        TODO(exchange-api-expert): ST3 — GET /v1/ticker 구현
        """
        return await self._execute_rest(self._do_get_ticker, market)

    async def _do_get_ticker(self, market: str) -> Ticker:
        """GET /v1/ticker?markets={market} 실행."""
        data = await self._request("GET", "/v1/ticker", params={"markets": market})
        if not isinstance(data, list) or not data:
            raise ExchangeDataError("upbit", "Empty ticker response")
        return parse_ticker(data[0])

    async def get_orderbook(self, market: str, depth: int = 10) -> OrderBook:
        """호가창 조회.

        TODO(exchange-api-expert): ST3 — GET /v1/orderbook 구현
        """
        return await self._execute_rest(self._do_get_orderbook, market, depth)

    async def _do_get_orderbook(self, market: str, depth: int) -> OrderBook:
        """GET /v1/orderbook?markets={market} 실행."""
        data = await self._request("GET", "/v1/orderbook", params={"markets": market})
        if not isinstance(data, list) or not data:
            raise ExchangeDataError("upbit", "Empty orderbook response")
        return parse_orderbook(data[0], depth=depth)

    async def get_candles(
        self, market: str, timeframe: str, count: int = 200
    ) -> list[Candle]:
        """OHLCV 캔들 데이터 조회.

        TODO(exchange-api-expert): ST3 — GET /v1/candles/* 구현
        """
        return await self._execute_rest(self._do_get_candles, market, timeframe, count)

    async def _do_get_candles(
        self, market: str, timeframe: str, count: int
    ) -> list[Candle]:
        """GET /v1/candles/{path}?market={market}&count={count} 실행."""
        candle_path = TIMEFRAME_TO_CANDLE_PATH.get(timeframe)
        if candle_path is None:
            raise ExchangeDataError("upbit", f"Unsupported timeframe: {timeframe}")
        data = await self._request(
            "GET",
            f"/v1/candles/{candle_path}",
            params={"market": market, "count": str(count)},
        )
        if not isinstance(data, list):
            raise ExchangeDataError("upbit", "Unexpected candles response format")
        return [parse_candle(item, market=market, timeframe=timeframe) for item in data]

    # ── REST: 주문 (ST5) ──────────────────────────────────────────────────────

    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행.

        Upbit ord_type 분기:
        - BUY + LIMIT  → side=bid, ord_type=limit
        - SELL + LIMIT → side=ask, ord_type=limit
        - BUY + MARKET → side=bid, ord_type=price (Order.price = 총 KRW 예산)
        - SELL + MARKET → side=ask, ord_type=market (Order.quantity = 코인 수량)

        Raises:
            ExchangeAuthError: API 키 인증 실패
            ExchangePermissionError: TRADE 권한 없음
            ExchangeInsufficientBalanceError: 잔고 부족
            ExchangeOrderError: 최소 주문 금액 미달 등
        """
        return await self._execute_rest(self._do_place_order, order)

    async def _do_place_order(self, order: Order) -> OrderResult:
        """POST /v1/orders 실행 + Upbit 주문 방식 분기 처리."""
        side = "bid" if order.side == OrderSide.BUY else "ask"

        if order.method == OrderMethod.LIMIT:
            if order.price is None:
                raise ExchangeOrderError("upbit", "price is required for LIMIT order")
            body: dict[str, Any] = {
                "market": order.market,
                "side": side,
                "ord_type": "limit",
                "price": str(order.price),
                "volume": str(order.quantity),
            }
        elif order.side == OrderSide.BUY:
            # 시장가 매수: ord_type=price, price=KRW 총 예산
            if order.price is None:
                raise ExchangeOrderError(
                    "upbit",
                    "price (KRW budget) is required for MARKET BUY order",
                )
            body = {
                "market": order.market,
                "side": side,
                "ord_type": "price",
                "price": str(order.price),
            }
        else:
            # 시장가 매도: ord_type=market, volume=수량
            body = {
                "market": order.market,
                "side": side,
                "ord_type": "market",
                "volume": str(order.quantity),
            }

        data = await self._request("POST", "/v1/orders", json_body=body, auth=True)
        return parse_order_result(data)

    async def cancel_order(self, market: str, exchange_order_id: str) -> bool:
        """주문 취소.

        Returns:
            True: 취소 성공
            False: 이미 체결된 주문 (상태가 done인 경우)
        """
        return await self._execute_rest(self._do_cancel_order, market, exchange_order_id)

    async def _do_cancel_order(self, market: str, exchange_order_id: str) -> bool:
        """DELETE /v1/order?uuid={order_id} 실행."""
        params = {"uuid": exchange_order_id}
        data = await self._request(
            "DELETE",
            "/v1/order",
            params=params,
            auth=True,
        )
        if not isinstance(data, dict):
            raise ExchangeDataError("upbit", "Unexpected cancel_order response format")
        state = data.get("state", "")
        # "cancel" 또는 "done" 상태가 반환되면 취소 처리 완료로 간주
        return state in ("cancel", "done")

    # ── REST: 잔고 / 수수료 (ST6) ─────────────────────────────────────────────

    async def get_balance(self) -> list[Balance]:
        """전체 잔고 조회.

        Returns:
            list[Balance]: 보유 자산 목록 (available > 0 또는 locked > 0 필터링)
        """
        return await self._execute_rest(self._do_get_balance)

    async def _do_get_balance(self) -> list[Balance]:
        """GET /v1/accounts 실행."""
        data = await self._request("GET", "/v1/accounts", auth=True)
        if not isinstance(data, list):
            raise ExchangeDataError("upbit", "Unexpected accounts response format")
        return [parse_balance(item) for item in data]

    async def get_trading_fee(self, market: str) -> TradingFee:
        """수수료 조회.

        GET /v1/orders/chance → ask_fee / bid_fee 추출.
        Upbit은 maker/taker 동일 수수료.
        """
        return await self._execute_rest(self._do_get_trading_fee, market)

    async def _do_get_trading_fee(self, market: str) -> TradingFee:
        """GET /v1/orders/chance?market={market} 실행."""
        params = {"market": market}
        data = await self._request(
            "GET",
            "/v1/orders/chance",
            params=params,
            auth=True,
        )
        if not isinstance(data, dict):
            raise ExchangeDataError("upbit", "Unexpected orders/chance response format")
        try:
            maker_fee = Decimal(str(data["bid_fee"]))  # 매수 수수료 = maker
            taker_fee = Decimal(str(data["ask_fee"]))  # 매도 수수료 = taker
        except (KeyError, TypeError, ValueError) as exc:
            raise ExchangeDataError("upbit", f"Failed to parse trading fee: {exc}") from exc
        return TradingFee(
            exchange=ExchangeType.UPBIT,
            market=market,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
        )

    # ── REST: API 키 검증 (exchange-api-expert ST7 담당) ─────────────────────

    async def verify_api_key(self) -> ApiKeyInfo:
        """API 키 유효성 및 권한 2단계 검증.

        1. GET /v1/api_keys → is_valid 결정
        2. GET /v1/accounts → VIEW_BALANCE 권한
        3. GET /v1/orders/chance → VIEW_ORDERS + TRADE 권한

        TODO(exchange-api-expert): ST7 — 상세 구현
        """
        return await self._execute_rest(self._do_verify_api_key)

    async def _do_verify_api_key(self) -> ApiKeyInfo:
        """2단계 API 키 권한 검증 실행."""
        permissions: list[ApiKeyPermission] = []

        # 1단계: API 키 유효성 확인
        try:
            await self._request("GET", "/v1/api_keys", auth=True)
        except ExchangeAuthError as exc:
            return ApiKeyInfo(
                exchange=ExchangeType.UPBIT,
                permissions=[],
                is_valid=False,
                error_message=str(exc),
                has_withdraw_permission=False,
            )

        # 2단계: 잔고 조회 권한
        try:
            await self._request("GET", "/v1/accounts", auth=True)
            permissions.append(ApiKeyPermission.VIEW_BALANCE)
        except (ExchangeAuthError, ExchangePermissionError, ExchangeNetworkError):
            pass

        # 3단계: 주문 권한
        try:
            params = {"market": "KRW-BTC"}
            await self._request(
                "GET",
                "/v1/orders/chance",
                params=params,
                auth=True,
            )
            permissions.append(ApiKeyPermission.VIEW_ORDERS)
            permissions.append(ApiKeyPermission.TRADE)
        except (ExchangeAuthError, ExchangePermissionError, ExchangeNetworkError):
            pass

        return ApiKeyInfo(
            exchange=ExchangeType.UPBIT,
            permissions=permissions,
            is_valid=True,
            has_withdraw_permission=False,  # Upbit API로 출금 권한 확인 불가
        )

    # ── WebSocket (exchange-api-expert ST4 담당) ──────────────────────────────

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

            self._ws = _UpbitWebSocketClient(
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
            markets: 거래소 마켓 코드 목록 e.g. ["KRW-BTC"]
            callback: 시세 수신 시 호출할 async 콜백
        """
        if self._ws is None:
            await self.connect()
        await self._ws.subscribe("ticker", markets, callback)  # type: ignore[union-attr]

    async def subscribe_orderbook(
        self,
        markets: list[str],
        callback: Callable[[OrderBook], Awaitable[None]],
    ) -> None:
        """실시간 호가창 구독."""
        if self._ws is None:
            await self.connect()
        await self._ws.subscribe("orderbook", markets, callback)  # type: ignore[union-attr]

    async def unsubscribe(self, markets: list[str] | None = None) -> None:
        """구독 해제.

        Args:
            markets: 해제할 마켓 목록. None 시 전체 해제.
        """
        if self._ws is not None:
            await self._ws.unsubscribe(markets)
