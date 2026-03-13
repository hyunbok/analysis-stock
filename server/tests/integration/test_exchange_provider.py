"""Exchange Provider 통합 테스트 — Mock Provider로 전체 흐름 검증."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import fakeredis.aioredis as fakeredis

from app.providers.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.providers.enums import ExchangeType, OrderMethod, OrderSide
from app.providers.exceptions import (
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from app.providers.factory import ExchangeProviderFactory, ExchangeProviderRegistry
from app.providers.mock_provider import MockExchangeProvider
from app.providers.types import Order


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_factory():
    """각 테스트 후 Factory 싱글턴 초기화."""
    original = ExchangeProviderRegistry._registry.copy()
    ExchangeProviderFactory._instance = None
    yield
    ExchangeProviderRegistry._registry = original
    ExchangeProviderFactory._instance = None


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def factory(redis_client):
    ExchangeProviderRegistry._registry.clear()
    f = ExchangeProviderFactory.init(redis=redis_client)
    f.register_defaults()
    return f


def make_provider(factory, exchange_type=ExchangeType.UPBIT, user_id="user-1"):
    return factory.create(
        exchange_type=exchange_type,
        api_key="test-key",
        api_secret="test-secret",
        user_id=user_id,
    )


# ── TC1: 시세 조회 전체 흐름 ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_full_ticker_flow(factory):
    """시세 조회 → Rate Limiter 통과 → Circuit Breaker 통과 → Ticker 반환."""
    provider = make_provider(factory)
    ticker = await provider._execute_rest(provider.get_ticker, "KRW-BTC")
    assert ticker.market == "KRW-BTC"
    assert ticker.price > Decimal("0")


@pytest.mark.anyio
async def test_ticker_multiple_markets(factory):
    """여러 마켓 시세 조회 모두 성공."""
    provider = make_provider(factory)
    for market in ["KRW-BTC", "KRW-ETH"]:
        ticker = await provider._execute_rest(provider.get_ticker, market)
        assert ticker.market == market


# ── TC2: 주문 실행 전체 흐름 ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_full_order_flow(factory):
    """주문 실행 → Circuit Breaker 통과 → OrderResult 반환."""
    provider = make_provider(factory)
    order = Order(
        market="KRW-BTC",
        side=OrderSide.BUY,
        method=OrderMethod.MARKET,
        quantity=Decimal("0.001"),
    )
    result = await provider._execute_rest(provider.place_order, order)
    assert result.market == "KRW-BTC"
    assert result.quantity == Decimal("0.001")


# ── TC3: Rate Limit 동작 ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_rate_limit_triggers_error(factory):
    """Rate Limiter가 거부할 때 ExchangeRateLimitError 발생."""
    from app.core.rate_limiter import RateLimitResult

    provider = make_provider(factory)

    with patch.object(
        provider._rate_limiter,
        "acquire",
        new=AsyncMock(
            return_value=RateLimitResult(allowed=False, remaining=0, retry_after_ms=1000)
        ),
    ):
        with pytest.raises(ExchangeRateLimitError) as exc_info:
            await provider._execute_rest(provider.get_ticker, "KRW-BTC")

    assert exc_info.value.retry_after_seconds == 1


# ── TC4: Circuit Breaker 트리거 ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_circuit_breaker_triggers_on_failures(factory):
    """연속 실패 시 Circuit Breaker OPEN → ExchangeUnavailableError."""
    from app.providers.enums import CircuitState

    # 빠르게 OPEN 트리거하기 위한 커스텀 CB 설정
    cb = CircuitBreaker(
        name="upbit",
        config=CircuitBreakerConfig(failure_threshold=3),
    )
    provider = MockExchangeProvider(
        exchange_type=ExchangeType.UPBIT,
        api_key="key",
        api_secret="secret",
        rate_limiter=factory._rate_limiter,
        circuit_breaker=cb,
        user_id="user-1",
    )

    async def failing_fn():
        raise RuntimeError("exchange down")

    # 3번 실패 → OPEN
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await provider._execute_rest(failing_fn)

    assert cb.state == CircuitState.OPEN

    # OPEN 상태에서 추가 호출 → ExchangeUnavailableError
    with pytest.raises(ExchangeUnavailableError):
        await provider._execute_rest(failing_fn)


# ── TC5: 거래소별 Circuit Breaker 독립성 ──────────────────────────────────────


@pytest.mark.anyio
async def test_circuit_breaker_isolation_per_exchange(factory):
    """한 거래소 Circuit Breaker OPEN이 다른 거래소에 영향 없음."""
    from app.providers.enums import CircuitState

    # UPBIT CB 수동 OPEN
    cb_upbit = factory.get_circuit_breaker(ExchangeType.UPBIT)
    cb_upbit.reset()

    for _ in range(5):
        try:
            await cb_upbit.call(AsyncMock(side_effect=RuntimeError("fail")))
        except RuntimeError:
            pass

    assert cb_upbit.state == CircuitState.OPEN

    # BINANCE CB는 여전히 CLOSED
    cb_binance = factory.get_circuit_breaker(ExchangeType.BINANCE)
    assert cb_binance.state == CircuitState.CLOSED

    # BINANCE Provider는 정상 동작
    binance_provider = make_provider(factory, ExchangeType.BINANCE, "user-2")
    ticker = await binance_provider._execute_rest(
        binance_provider.get_ticker, "BTCUSDT"
    )
    assert ticker.market == "BTCUSDT"


# ── TC6: Factory create_from_account ─────────────────────────────────────────


@pytest.mark.anyio
async def test_create_from_account(factory):
    """UserExchangeAccount에서 복호화 후 Provider 생성."""
    import os
    from unittest.mock import MagicMock

    from app.core.encryption import encrypt_value

    # 32바이트 테스트 키 생성
    test_key = os.urandom(32)
    encrypted_api_key = encrypt_value("my-api-key", test_key)
    encrypted_api_secret = encrypt_value("my-api-secret", test_key)

    account = MagicMock()
    account.exchange_type = "upbit"
    account.api_key_encrypted = encrypted_api_key
    account.api_secret_encrypted = encrypted_api_secret
    account.user_id = "user-uuid"

    provider = await factory.create_from_account(account, test_key)
    assert provider.exchange_type == ExchangeType.UPBIT


# ── TC7: WebSocket 구독 전체 흐름 ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_ws_subscribe_ticker_flow(factory):
    """WebSocket 연결 → 시세 구독 → 콜백 수신."""
    provider = make_provider(factory)

    received = []

    async def callback(ticker):
        received.append(ticker)

    await provider.connect()
    assert provider.is_connected

    await provider.subscribe_ticker(["KRW-BTC"], callback)
    assert len(received) == 1
    assert received[0].market == "KRW-BTC"

    await provider.disconnect()
    assert not provider.is_connected


# ── TC8: 잔고 조회 흐름 ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_balance_flow(factory):
    """잔고 조회 전체 흐름."""
    provider = make_provider(factory)
    balances = await provider._execute_rest(provider.get_balance)
    assert len(balances) > 0
    total_krw = next(
        (b.available for b in balances if b.currency == "KRW"), Decimal("0")
    )
    assert total_krw > Decimal("0")
