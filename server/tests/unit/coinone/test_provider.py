"""CoinOneProvider 단위 테스트 — httpx MockTransport으로 REST 메서드 검증."""
from __future__ import annotations

import json
from decimal import Decimal

import fakeredis.aioredis as fakeredis
import httpx
import pytest

from app.core.rate_limiter import ExchangeRateLimiter
from app.providers.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.providers.enums import ApiKeyPermission, ExchangeType, OrderMethod, OrderSide
from app.providers.exceptions import (
    ExchangeAuthError,
    ExchangeInsufficientBalanceError,
)
from app.providers.types import Order
from app.providers.coinone.provider import CoinOneProvider


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


def _make_provider(
    redis_client,
    mock_transport: httpx.MockTransport,
) -> CoinOneProvider:
    """CoinOneProvider with injected mock HTTP transport."""
    cb = CircuitBreaker(name="coinone-test", config=CircuitBreakerConfig())
    provider = CoinOneProvider(
        exchange_type=ExchangeType.COINONE,
        api_key="test-access-token",
        api_secret="test-secret-key",
        rate_limiter=ExchangeRateLimiter(redis_client),
        circuit_breaker=cb,
        user_id="user-123",
    )
    # httpx 클라이언트를 mock transport으로 교체
    provider._http_client = httpx.AsyncClient(transport=mock_transport)
    return provider


def _response(body: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=body)


# ── TC1: 시세 조회 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_ticker(redis_client) -> None:
    """정상 시세 조회."""
    payload = {
        "result": "success",
        "error_code": "0",
        "tickers": [
            {
                "quote_currency": "KRW",
                "target_currency": "BTC",
                "timestamp": 1710000000000,
                "high": "96000000",
                "low": "92000000",
                "first": "93000000",
                "last": "95000000",
                "quote_volume": "11723000000",
                "target_volume": "123.4",
            }
        ],
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    ticker = await provider.get_ticker("BTC")
    assert ticker.market == "BTC"
    assert ticker.price == Decimal("95000000")
    assert ticker.exchange == ExchangeType.COINONE


# ── TC2: 호가 조회 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_orderbook(redis_client) -> None:
    """정상 호가 조회 — asks 오름차순, bids 내림차순 정렬."""
    payload = {
        "result": "success",
        "error_code": "0",
        "timestamp": 1710000000000,
        "quote_currency": "KRW",
        "target_currency": "BTC",
        "asks": [
            {"price": "95200000", "qty": "1.0"},
            {"price": "95100000", "qty": "0.5"},
        ],
        "bids": [
            {"price": "94800000", "qty": "0.7"},
            {"price": "94900000", "qty": "0.3"},
        ],
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    ob = await provider.get_orderbook("BTC", depth=5)
    assert ob.market == "BTC"
    assert ob.exchange == ExchangeType.COINONE
    assert len(ob.asks) >= 1
    # 오름차순 정렬: 낮은 asks[0]
    assert ob.asks[0].price == Decimal("95100000")
    # 내림차순 정렬: 높은 bids[0]
    assert ob.bids[0].price == Decimal("94900000")


# ── TC3: 캔들 조회 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_candles_1h(redis_client) -> None:
    """1시간봉 조회 — interval=1h 쿼리 파라미터 확인."""
    payload = {
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
                "quote_volume": "11723000000",
            }
        ],
    }
    requests_seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests_seen.append(str(req.url))
        return _response(payload)

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    candles = await provider.get_candles("BTC", "1h")
    assert len(candles) == 1
    assert candles[0].timeframe == "1h"
    assert "interval=1h" in requests_seen[0]


@pytest.mark.anyio
async def test_get_candles_1d(redis_client) -> None:
    """일봉 조회 — interval=1d."""
    payload = {
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
                "quote_volume": "11723000000",
            }
        ],
    }
    requests_seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests_seen.append(str(req.url))
        return _response(payload)

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    candles = await provider.get_candles("BTC", "1d")
    assert len(candles) == 1
    assert "interval=1d" in requests_seen[0]


# ── TC4: 주문 생성 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_place_order_limit_buy(redis_client) -> None:
    """지정가 매수 — side=BUY, type=LIMIT, price+qty."""
    payload = {
        "result": "success",
        "error_code": "0",
        "order_id": "limit-buy-order-uuid",
    }
    requests_seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        requests_seen.append(body)
        return _response(payload, 201)

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="BTC",
        side=OrderSide.BUY,
        method=OrderMethod.LIMIT,
        quantity=Decimal("0.001"),
        price=Decimal("95000000"),
    )
    result = await provider.place_order(order)
    assert result.exchange_order_id == "limit-buy-order-uuid"
    assert requests_seen[0]["side"] == "BUY"
    assert requests_seen[0]["type"] == "LIMIT"
    assert requests_seen[0]["price"] == "95000000"
    assert requests_seen[0]["qty"] == "0.001"


@pytest.mark.anyio
async def test_place_order_limit_sell(redis_client) -> None:
    """지정가 매도 — side=SELL, type=LIMIT, price+qty."""
    payload = {
        "result": "success",
        "error_code": "0",
        "order_id": "limit-sell-order-uuid",
    }
    requests_seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        requests_seen.append(body)
        return _response(payload, 201)

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="BTC",
        side=OrderSide.SELL,
        method=OrderMethod.LIMIT,
        quantity=Decimal("0.001"),
        price=Decimal("95000000"),
    )
    result = await provider.place_order(order)
    assert result.exchange_order_id == "limit-sell-order-uuid"
    assert requests_seen[0]["side"] == "SELL"
    assert requests_seen[0]["type"] == "LIMIT"
    assert requests_seen[0]["price"] == "95000000"
    assert requests_seen[0]["qty"] == "0.001"


@pytest.mark.anyio
async def test_place_order_market_buy(redis_client) -> None:
    """시장가 매수 — type=MARKET, amount=총 KRW 예산 (qty 없음)."""
    payload = {
        "result": "success",
        "error_code": "0",
        "order_id": "market-buy-order-uuid",
    }
    requests_seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        requests_seen.append(body)
        return _response(payload, 201)

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="BTC",
        side=OrderSide.BUY,
        method=OrderMethod.MARKET,
        quantity=Decimal("0"),  # 시장가 매수에서 미사용
        price=Decimal("100000"),  # KRW 총 예산
    )
    result = await provider.place_order(order)
    assert requests_seen[0]["side"] == "BUY"
    assert requests_seen[0]["type"] == "MARKET"
    assert requests_seen[0]["amount"] == "100000"
    assert "qty" not in requests_seen[0]
    assert "price" not in requests_seen[0]


@pytest.mark.anyio
async def test_place_order_market_sell(redis_client) -> None:
    """시장가 매도 — type=MARKET, qty=코인 수량 (amount 없음)."""
    payload = {
        "result": "success",
        "error_code": "0",
        "order_id": "market-sell-order-uuid",
    }
    requests_seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        requests_seen.append(body)
        return _response(payload, 201)

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="BTC",
        side=OrderSide.SELL,
        method=OrderMethod.MARKET,
        quantity=Decimal("0.001"),
    )
    result = await provider.place_order(order)
    assert requests_seen[0]["side"] == "SELL"
    assert requests_seen[0]["type"] == "MARKET"
    assert requests_seen[0]["qty"] == "0.001"
    assert "amount" not in requests_seen[0]
    assert "price" not in requests_seen[0]


# ── TC5: 주문 취소 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_cancel_order(redis_client) -> None:
    """주문 취소 성공 — remain_qty > 0, traded_qty = "0" → CANCELLED."""
    payload = {
        "result": "success",
        "error_code": "0",
        "order_id": "cancel-order-uuid",
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
        "ordered_at": 1709999000000,
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    result = await provider.cancel_order("BTC", "cancel-order-uuid")
    assert result is True


# ── TC6: 잔고 조회 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_balance(redis_client) -> None:
    """잔고 조회 — limit 필드 → locked 매핑 확인."""
    payload = {
        "result": "success",
        "error_code": "0",
        "balances": [
            {"currency": "KRW", "available": "10000000", "limit": "0"},
            {"currency": "BTC", "available": "0.1", "limit": "0.01"},
        ],
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    balances = await provider.get_balance()
    assert len(balances) == 2
    currencies = [b.currency for b in balances]
    assert "KRW" in currencies
    assert "BTC" in currencies
    # CoinOne "limit" → locked 매핑
    btc = next(b for b in balances if b.currency == "BTC")
    assert btc.locked == Decimal("0.01")


# ── TC7: 수수료 조회 ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_trading_fee(redis_client) -> None:
    """수수료 조회 — maker_fee, taker_fee 확인."""
    payload = {
        "result": "success",
        "error_code": "0",
        "maker_fee": "0.0002",
        "taker_fee": "0.0002",
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    fee = await provider.get_trading_fee("BTC")
    assert fee.market == "BTC"
    assert fee.maker_fee == Decimal("0.0002")
    assert fee.taker_fee == Decimal("0.0002")
    assert fee.exchange == ExchangeType.COINONE


# ── TC8: API 키 검증 ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_verify_api_key_valid(redis_client) -> None:
    """유효한 API 키 — balance + trade_fee 성공 → VIEW_BALANCE + TRADE 권한."""

    def handler(req: httpx.Request) -> httpx.Response:
        if "balance" in str(req.url):
            return _response({
                "result": "success",
                "error_code": "0",
                "balances": [{"currency": "KRW", "available": "1000000", "limit": "0"}],
            })
        elif "trade_fee" in str(req.url):
            return _response({
                "result": "success",
                "error_code": "0",
                "maker_fee": "0.0002",
                "taker_fee": "0.0002",
            })
        return _response({"result": "success", "error_code": "0"})

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    info = await provider.verify_api_key()
    assert info.is_valid is True
    assert ApiKeyPermission.VIEW_BALANCE in info.permissions
    assert ApiKeyPermission.TRADE in info.permissions
    assert ApiKeyPermission.VIEW_ORDERS in info.permissions
    assert info.has_withdraw_permission is False


@pytest.mark.anyio
async def test_verify_api_key_invalid(redis_client) -> None:
    """유효하지 않은 API 키 — error_code=12 → is_valid=False."""
    payload = {
        "result": "error",
        "error_code": "12",
        "error_msg": "Invalid access token",
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    info = await provider.verify_api_key()
    assert info.is_valid is False
    assert info.permissions == []
    assert info.error_message is not None


# ── TC9: 에러 처리 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_error_mapping_http200_error(redis_client) -> None:
    """CoinOne 고유: HTTP 200 + result='error' → error_code 기반 예외 변환."""
    # error_code=12 → ExchangeAuthError (HTTP 200이지만 에러 응답)
    payload = {
        "result": "error",
        "error_code": "12",
        "error_msg": "Invalid access token",
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    with pytest.raises(ExchangeAuthError):
        await provider.get_balance()


@pytest.mark.anyio
async def test_error_mapping_auth_error(redis_client) -> None:
    """error_code=12 → ExchangeAuthError (HTTP 상태 코드 무관)."""
    payload = {
        "result": "error",
        "error_code": "12",
        "error_msg": "Invalid access token",
    }
    transport = httpx.MockTransport(lambda req: _response(payload, 401))
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="BTC",
        side=OrderSide.BUY,
        method=OrderMethod.LIMIT,
        quantity=Decimal("0.001"),
        price=Decimal("95000000"),
    )
    with pytest.raises(ExchangeAuthError):
        await provider.place_order(order)


@pytest.mark.anyio
async def test_error_mapping_insufficient_balance(redis_client) -> None:
    """error_code=103 → ExchangeInsufficientBalanceError."""
    payload = {
        "result": "error",
        "error_code": "103",
        "error_msg": "Lack of Balance",
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="BTC",
        side=OrderSide.BUY,
        method=OrderMethod.LIMIT,
        quantity=Decimal("1000"),
        price=Decimal("95000000"),
    )
    with pytest.raises(ExchangeInsufficientBalanceError):
        await provider.place_order(order)


# ── TC10: initialize() ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_initialize_loads_markets(redis_client) -> None:
    """initialize() 시 GET /public/v2/markets/KRW → SymbolMapper에 CoinOne 마켓 등록."""
    from app.providers.types import SymbolMapper

    # 전역 상태 변경 전 원본 보존 (테스트 격리)
    original_map = SymbolMapper._MAPS.get(ExchangeType.COINONE, {}).copy()
    original_reverse = SymbolMapper._REVERSE.copy()

    try:
        markets_payload = {
            "result": "success",
            "error_code": "0",
            "markets": [
                {"target_currency": "BTC"},
                {"target_currency": "ETH"},
                {"target_currency": "XRP"},
            ],
        }
        transport = httpx.MockTransport(lambda req: _response(markets_payload))
        provider = _make_provider(redis_client, transport)

        await provider.initialize()

        coinone_map = SymbolMapper._MAPS.get(ExchangeType.COINONE, {})
        assert "BTC/KRW" in coinone_map
        assert coinone_map["BTC/KRW"] == "BTC"
        assert "ETH/KRW" in coinone_map
        assert "XRP/KRW" in coinone_map
        # 역방향 캐시 클리어 후 to_symbol 가능 확인
        SymbolMapper._REVERSE = {}
        symbol = SymbolMapper.to_symbol(ExchangeType.COINONE, "BTC")
        assert symbol == "BTC/KRW"
    finally:
        # 전역 상태 복원
        SymbolMapper._MAPS[ExchangeType.COINONE] = original_map
        SymbolMapper._REVERSE = original_reverse
