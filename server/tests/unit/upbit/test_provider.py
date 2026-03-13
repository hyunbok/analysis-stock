"""UpbitProvider 단위 테스트 — httpx MockTransport으로 REST 메서드 검증."""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis as fakeredis
import httpx
import pytest

from app.core.rate_limiter import ExchangeRateLimiter
from app.providers.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.providers.enums import ExchangeType, OrderMethod, OrderSide
from app.providers.exceptions import (
    ExchangeAuthError,
    ExchangeInsufficientBalanceError,
)
from app.providers.types import Order
from app.providers.upbit.provider import UpbitProvider


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


def _make_provider(
    redis_client,
    mock_transport: httpx.MockTransport,
) -> UpbitProvider:
    """UpbitProvider with injected mock HTTP transport."""
    cb = CircuitBreaker(name="upbit-test", config=CircuitBreakerConfig())
    provider = UpbitProvider(
        exchange_type=ExchangeType.UPBIT,
        api_key="test-key",
        api_secret="test-secret",
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
    payload = [
        {
            "market": "KRW-BTC",
            "trade_price": 95000000.0,
            "opening_price": 93000000.0,
            "high_price": 96000000.0,
            "low_price": 92000000.0,
            "acc_trade_volume_24h": 123.4,
            "acc_trade_price_24h": 11723000000.0,
            "signed_change_rate": 0.0215,
            "trade_timestamp": 1710000000000,
        }
    ]
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    ticker = await provider.get_ticker("KRW-BTC")
    assert ticker.market == "KRW-BTC"
    assert ticker.price == Decimal("95000000.0")


# ── TC2: 호가 조회 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_orderbook(redis_client) -> None:
    """정상 호가 조회."""
    payload = [
        {
            "market": "KRW-BTC",
            "timestamp": 1710000000000,
            "orderbook_units": [
                {
                    "ask_price": 95100000,
                    "bid_price": 94900000,
                    "ask_size": 0.5,
                    "bid_size": 0.3,
                }
            ],
        }
    ]
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    ob = await provider.get_orderbook("KRW-BTC", depth=5)
    assert ob.market == "KRW-BTC"
    assert len(ob.asks) == 1
    assert ob.asks[0].price == Decimal("95100000")


# ── TC3: 캔들 조회 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_candles_1m(redis_client) -> None:
    """1분봉 조회."""
    payload = [
        {
            "market": "KRW-BTC",
            "candle_date_time_utc": "2024-03-10T00:00:00",
            "opening_price": 93000000.0,
            "high_price": 96000000.0,
            "low_price": 92000000.0,
            "trade_price": 95000000.0,
            "candle_acc_trade_volume": 123.4,
        }
    ]
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    candles = await provider.get_candles("KRW-BTC", "1m")
    assert len(candles) == 1
    assert candles[0].timeframe == "1m"
    # URL에 minutes/1 포함 확인은 transport 레벨에서 가능하지만 여기서는 응답 검증만


@pytest.mark.anyio
async def test_get_candles_1d(redis_client) -> None:
    """일봉 조회 — 경로 분기 (days)."""
    requests_seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests_seen.append(str(req.url))
        return _response([
            {
                "market": "KRW-BTC",
                "candle_date_time_utc": "2024-03-10T00:00:00",
                "opening_price": 93000000.0,
                "high_price": 96000000.0,
                "low_price": 92000000.0,
                "trade_price": 95000000.0,
                "candle_acc_trade_volume": 123.4,
            }
        ])

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    candles = await provider.get_candles("KRW-BTC", "1d")
    assert len(candles) == 1
    assert "/candles/days" in requests_seen[0]


# ── TC4: 주문 생성 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_place_order_limit_buy(redis_client) -> None:
    """지정가 매수 주문."""
    payload = {
        "uuid": "limit-buy-uuid",
        "market": "KRW-BTC",
        "side": "bid",
        "ord_type": "limit",
        "state": "wait",
        "volume": "0.001",
        "executed_volume": "0.0",
        "price": "95000000",
        "avg_buy_price": "0",
        "paid_fee": "0",
        "created_at": "2024-03-10T10:00:00+09:00",
    }
    requests_seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        requests_seen.append(body)
        return _response(payload, 201)

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="KRW-BTC",
        side=OrderSide.BUY,
        method=OrderMethod.LIMIT,
        quantity=Decimal("0.001"),
        price=Decimal("95000000"),
    )
    result = await provider.place_order(order)
    assert result.exchange_order_id == "limit-buy-uuid"
    assert requests_seen[0]["ord_type"] == "limit"
    assert requests_seen[0]["side"] == "bid"


@pytest.mark.anyio
async def test_place_order_market_buy(redis_client) -> None:
    """시장가 매수 — ord_type=price, price=KRW 예산."""
    payload = {
        "uuid": "market-buy-uuid",
        "market": "KRW-BTC",
        "side": "bid",
        "ord_type": "price",
        "state": "done",
        "volume": None,
        "executed_volume": "0.001",
        "price": "95000",
        "avg_buy_price": "95000000",
        "paid_fee": "47.5",
        "created_at": "2024-03-10T10:00:00+09:00",
    }
    requests_seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        requests_seen.append(body)
        return _response(payload, 201)

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="KRW-BTC",
        side=OrderSide.BUY,
        method=OrderMethod.MARKET,
        quantity=Decimal("0"),  # 시장가 매수에서 미사용
        price=Decimal("95000"),  # KRW 예산
    )
    result = await provider.place_order(order)
    assert requests_seen[0]["ord_type"] == "price"
    assert requests_seen[0]["price"] == "95000"
    assert "volume" not in requests_seen[0]


@pytest.mark.anyio
async def test_place_order_market_sell(redis_client) -> None:
    """시장가 매도 — ord_type=market, volume=코인 수량."""
    payload = {
        "uuid": "market-sell-uuid",
        "market": "KRW-BTC",
        "side": "ask",
        "ord_type": "market",
        "state": "done",
        "volume": "0.001",
        "executed_volume": "0.001",
        "price": None,
        "avg_buy_price": "95000000",
        "paid_fee": "47.5",
        "created_at": "2024-03-10T10:00:00+09:00",
    }
    requests_seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        requests_seen.append(body)
        return _response(payload, 201)

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="KRW-BTC",
        side=OrderSide.SELL,
        method=OrderMethod.MARKET,
        quantity=Decimal("0.001"),
    )
    result = await provider.place_order(order)
    assert requests_seen[0]["ord_type"] == "market"
    assert requests_seen[0]["side"] == "ask"
    assert "price" not in requests_seen[0]


# ── TC5: 주문 취소 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_cancel_order(redis_client) -> None:
    """주문 취소 성공."""
    payload = {
        "uuid": "cancel-uuid",
        "market": "KRW-BTC",
        "state": "cancel",
        "side": "bid",
        "ord_type": "limit",
        "volume": "0.001",
        "executed_volume": "0.0",
        "price": "95000000",
        "avg_buy_price": "0",
        "paid_fee": "0",
        "created_at": "2024-03-10T10:00:00+09:00",
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    result = await provider.cancel_order("KRW-BTC", "cancel-uuid")
    assert result is True


# ── TC6: 잔고 조회 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_balance(redis_client) -> None:
    """잔고 조회."""
    payload = [
        {"currency": "KRW", "balance": "10000000.0", "locked": "0.0"},
        {"currency": "BTC", "balance": "0.1", "locked": "0.0"},
    ]
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    balances = await provider.get_balance()
    assert len(balances) == 2
    currencies = [b.currency for b in balances]
    assert "KRW" in currencies
    assert "BTC" in currencies


# ── TC7: 수수료 조회 ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_trading_fee(redis_client) -> None:
    """수수료 조회."""
    payload = {
        "ask_fee": "0.0005",
        "bid_fee": "0.0005",
        "market": {"id": "KRW-BTC"},
    }
    transport = httpx.MockTransport(lambda req: _response(payload))
    provider = _make_provider(redis_client, transport)

    fee = await provider.get_trading_fee("KRW-BTC")
    assert fee.market == "KRW-BTC"
    assert fee.maker_fee == Decimal("0.0005")
    assert fee.taker_fee == Decimal("0.0005")


# ── TC8: API 키 검증 ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_verify_api_key_valid(redis_client) -> None:
    """유효한 API 키 — 3단계 모두 성공."""
    from app.providers.enums import ApiKeyPermission

    call_count = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if "api_keys" in str(req.url):
            return _response([{"access_key": "test-key"}])
        elif "accounts" in str(req.url):
            return _response([{"currency": "KRW", "balance": "1000000", "locked": "0"}])
        elif "orders/chance" in str(req.url):
            return _response({"ask_fee": "0.0005", "bid_fee": "0.0005", "market": {}})
        return _response({})

    transport = httpx.MockTransport(handler)
    provider = _make_provider(redis_client, transport)

    info = await provider.verify_api_key()
    assert info.is_valid is True
    assert ApiKeyPermission.VIEW_BALANCE in info.permissions
    assert ApiKeyPermission.TRADE in info.permissions
    assert info.has_withdraw_permission is False


# ── TC9: 에러 처리 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_error_mapping_auth_401(redis_client) -> None:
    """401 응답 → ExchangeAuthError 변환."""
    error_payload = {
        "error": {
            "name": "invalid_access_key",
            "message": "Access key does not exist.",
        }
    }
    transport = httpx.MockTransport(lambda req: _response(error_payload, 401))
    provider = _make_provider(redis_client, transport)

    with pytest.raises(ExchangeAuthError):
        await provider.get_balance()


@pytest.mark.anyio
async def test_error_mapping_insufficient_funds(redis_client) -> None:
    """insufficient_funds_bid → ExchangeInsufficientBalanceError."""
    error_payload = {
        "error": {
            "name": "insufficient_funds_bid",
            "message": "Insufficient funds.",
        }
    }
    transport = httpx.MockTransport(lambda req: _response(error_payload, 400))
    provider = _make_provider(redis_client, transport)

    order = Order(
        market="KRW-BTC",
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
    """initialize() 시 SymbolMapper에 Upbit 마켓 등록."""
    from app.providers.types import SymbolMapper

    markets_payload = [
        {"market": "KRW-BTC", "korean_name": "비트코인"},
        {"market": "KRW-ETH", "korean_name": "이더리움"},
        {"market": "KRW-SOL", "korean_name": "솔라나"},
        {"market": "BTC-ETH", "korean_name": "이더리움"},  # KRW 마켓이 아님 — 제외
    ]
    transport = httpx.MockTransport(lambda req: _response(markets_payload))
    provider = _make_provider(redis_client, transport)

    await provider.initialize()

    upbit_map = SymbolMapper._MAPS.get(ExchangeType.UPBIT, {})
    assert "BTC/KRW" in upbit_map
    assert upbit_map["BTC/KRW"] == "KRW-BTC"
    assert "ETH/KRW" in upbit_map
    assert "SOL/KRW" in upbit_map
    # KRW 마켓이 아닌 BTC-ETH는 포함되지 않아야 함
    assert "ETH/BTC" not in upbit_map
