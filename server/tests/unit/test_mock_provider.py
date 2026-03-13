"""Mock Exchange Provider 단위 테스트."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import fakeredis.aioredis as fakeredis

from app.providers.base import ExchangeProvider
from app.providers.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.providers.enums import (
    ApiKeyPermission,
    ExchangeType,
    OrderMethod,
    OrderSide,
    OrderStatus,
)
from app.providers.mock_provider import MockExchangeProvider
from app.providers.types import Order


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_provider(redis_client):
    from app.core.rate_limiter import ExchangeRateLimiter

    cb = CircuitBreaker(
        name="mock",
        config=CircuitBreakerConfig(),
    )
    return MockExchangeProvider(
        exchange_type=ExchangeType.UPBIT,
        api_key="test-key",
        api_secret="test-secret",
        rate_limiter=ExchangeRateLimiter(redis_client),
        circuit_breaker=cb,
        user_id="user-123",
    )


# ── TC1: ABC 준수 검증 ────────────────────────────────────────────────────────


def test_mock_provider_is_exchange_provider(mock_provider):
    """MockExchangeProvider가 ExchangeProvider ABC를 구현."""
    assert isinstance(mock_provider, ExchangeProvider)


def test_mock_provider_exchange_type(mock_provider):
    """exchange_type 프로퍼티 올바른 값 반환."""
    assert mock_provider.exchange_type == ExchangeType.UPBIT


# ── TC2: REST API 메서드 ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_ticker_returns_ticker(mock_provider):
    """get_ticker()가 Ticker 모델 반환."""
    from app.providers.types import Ticker

    ticker = await mock_provider.get_ticker("KRW-BTC")
    assert isinstance(ticker, Ticker)
    assert ticker.market == "KRW-BTC"
    assert ticker.exchange == ExchangeType.UPBIT
    assert ticker.price > Decimal("0")


@pytest.mark.anyio
async def test_get_ticker_known_market_has_correct_price(mock_provider):
    """알려진 마켓 코드에 대해 시뮬레이션 가격 반환."""
    ticker = await mock_provider.get_ticker("KRW-BTC")
    assert ticker.price == Decimal("95000000")


@pytest.mark.anyio
async def test_get_orderbook_returns_orderbook(mock_provider):
    """get_orderbook()이 OrderBook 모델 반환."""
    from app.providers.types import OrderBook

    ob = await mock_provider.get_orderbook("KRW-BTC", depth=5)
    assert isinstance(ob, OrderBook)
    assert len(ob.asks) == 5
    assert len(ob.bids) == 5
    # 매도 > 매수 (호가창 정렬 검증)
    assert ob.asks[0].price > ob.bids[0].price


@pytest.mark.anyio
async def test_get_candles_returns_list(mock_provider):
    """get_candles()이 요청한 수의 Candle 목록 반환."""
    candles = await mock_provider.get_candles("KRW-BTC", "1h", count=50)
    assert len(candles) == 50
    for candle in candles:
        assert candle.timeframe == "1h"
        assert candle.market == "KRW-BTC"


@pytest.mark.anyio
async def test_place_market_order(mock_provider):
    """시장가 주문 실행 — FILLED 상태로 반환."""
    order = Order(
        market="KRW-BTC",
        side=OrderSide.BUY,
        method=OrderMethod.MARKET,
        quantity=Decimal("0.001"),
    )
    result = await mock_provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.executed_quantity == Decimal("0.001")
    assert result.exchange_order_id  # 비어있지 않음


@pytest.mark.anyio
async def test_place_limit_order(mock_provider):
    """지정가 주문 실행 — 요청 가격 그대로 반환."""
    order = Order(
        market="KRW-BTC",
        side=OrderSide.SELL,
        method=OrderMethod.LIMIT,
        quantity=Decimal("0.01"),
        price=Decimal("96000000"),
    )
    result = await mock_provider.place_order(order)
    assert result.price == Decimal("96000000")
    assert result.status == OrderStatus.FILLED


@pytest.mark.anyio
async def test_cancel_order_returns_true(mock_provider):
    """주문 취소 항상 True 반환."""
    result = await mock_provider.cancel_order("KRW-BTC", "order-123")
    assert result is True


@pytest.mark.anyio
async def test_get_balance_returns_balances(mock_provider):
    """잔고 조회 — 기본 보유 자산 목록 반환."""
    balances = await mock_provider.get_balance()
    assert len(balances) >= 1
    currencies = [b.currency for b in balances]
    assert "KRW" in currencies


@pytest.mark.anyio
async def test_get_trading_fee(mock_provider):
    """수수료 조회 — 양수 수수료 반환."""
    fee = await mock_provider.get_trading_fee("KRW-BTC")
    assert fee.maker_fee > Decimal("0")
    assert fee.taker_fee >= fee.maker_fee


@pytest.mark.anyio
async def test_verify_api_key_valid(mock_provider):
    """API 키 검증 — 유효한 키로 반환."""
    info = await mock_provider.verify_api_key()
    assert info.is_valid
    assert ApiKeyPermission.TRADE in info.permissions
    assert not info.has_withdraw_permission


# ── TC3: WebSocket 메서드 ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_connect_sets_ws_connected(mock_provider):
    """connect() 후 is_connected = True."""
    assert not mock_provider.is_connected
    await mock_provider.connect()
    assert mock_provider.is_connected


@pytest.mark.anyio
async def test_disconnect_clears_ws_connected(mock_provider):
    """disconnect() 후 is_connected = False."""
    await mock_provider.connect()
    await mock_provider.disconnect()
    assert not mock_provider.is_connected


@pytest.mark.anyio
async def test_subscribe_ticker_calls_callback(mock_provider):
    """subscribe_ticker()가 콜백으로 Ticker 전달."""
    received = []

    async def callback(ticker):
        received.append(ticker)

    await mock_provider.subscribe_ticker(["KRW-BTC", "KRW-ETH"], callback)
    assert len(received) == 2
    markets = [t.market for t in received]
    assert "KRW-BTC" in markets
    assert "KRW-ETH" in markets


@pytest.mark.anyio
async def test_subscribe_orderbook_calls_callback(mock_provider):
    """subscribe_orderbook()가 콜백으로 OrderBook 전달."""
    received = []

    async def callback(ob):
        received.append(ob)

    await mock_provider.subscribe_orderbook(["KRW-BTC"], callback)
    assert len(received) == 1
    assert received[0].market == "KRW-BTC"


@pytest.mark.anyio
async def test_unsubscribe_does_not_raise(mock_provider):
    """unsubscribe()가 예외 없이 완료."""
    await mock_provider.unsubscribe(["KRW-BTC"])
    await mock_provider.unsubscribe()  # 전체 해제


# ── TC4: initialize / close ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_initialize_prepares_http_client(mock_provider):
    """initialize() 후 HTTP 클라이언트 준비."""
    await mock_provider.initialize()
    assert mock_provider._http_client is not None
    assert not mock_provider._http_client.is_closed


@pytest.mark.anyio
async def test_close_shuts_down_http_client(mock_provider):
    """close() 후 HTTP 클라이언트 종료."""
    await mock_provider.initialize()
    await mock_provider.close()
    assert mock_provider._http_client.is_closed


@pytest.mark.anyio
async def test_close_also_disconnects_ws(mock_provider):
    """close() 시 WS 연결도 해제."""
    await mock_provider.connect()
    assert mock_provider.is_connected
    await mock_provider.close()
    assert not mock_provider.is_connected
