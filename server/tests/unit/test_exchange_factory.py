"""Exchange Provider Factory + Registry 단위 테스트."""
from __future__ import annotations

import pytest
import fakeredis.aioredis as fakeredis

from app.providers.circuit_breaker import CircuitBreakerConfig
from app.providers.enums import ExchangeType
from app.providers.factory import (
    ExchangeProviderFactory,
    ExchangeProviderRegistry,
)
from app.providers.mock_provider import MockExchangeProvider


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_registry_and_factory():
    """각 테스트 전후 Registry 및 Factory 싱글턴 초기화."""
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


# ── TC1: Registry 등록/조회 ───────────────────────────────────────────────────


def test_registry_register_and_get():
    """ExchangeProviderRegistry.register 데코레이터 + get() 동작."""
    ExchangeProviderRegistry._registry.clear()

    @ExchangeProviderRegistry.register(ExchangeType.UPBIT)
    class DummyProvider(MockExchangeProvider):
        pass

    assert ExchangeProviderRegistry.get(ExchangeType.UPBIT) is DummyProvider


def test_registry_get_unregistered_raises():
    """미등록 거래소 조회 시 KeyError."""
    ExchangeProviderRegistry._registry.clear()
    with pytest.raises(KeyError, match="upbit"):
        ExchangeProviderRegistry.get(ExchangeType.UPBIT)


def test_registry_registered_exchanges():
    """registered_exchanges()가 등록된 목록 반환."""
    ExchangeProviderRegistry._registry.clear()
    ExchangeProviderRegistry._registry[ExchangeType.UPBIT] = MockExchangeProvider
    ExchangeProviderRegistry._registry[ExchangeType.BINANCE] = MockExchangeProvider

    registered = ExchangeProviderRegistry.registered_exchanges()
    assert ExchangeType.UPBIT in registered
    assert ExchangeType.BINANCE in registered


# ── TC2: Factory 싱글턴 ───────────────────────────────────────────────────────


def test_factory_singleton(redis_client):
    """init() 후 instance()가 동일 인스턴스 반환."""
    f1 = ExchangeProviderFactory.init(redis=redis_client)
    f2 = ExchangeProviderFactory.instance()
    assert f1 is f2


def test_factory_instance_before_init_raises():
    """init() 호출 전 instance() 접근 시 RuntimeError."""
    ExchangeProviderFactory._instance = None
    with pytest.raises(RuntimeError, match="not initialized"):
        ExchangeProviderFactory.instance()


# ── TC3: register_defaults() ─────────────────────────────────────────────────


def test_register_defaults_fills_all_exchanges(factory):
    """register_defaults() 호출 후 모든 거래소가 MockProvider로 등록."""
    for exchange_type in ExchangeType:
        cls = ExchangeProviderRegistry.get(exchange_type)
        assert cls is MockExchangeProvider


def test_register_defaults_does_not_overwrite_existing(redis_client):
    """이미 등록된 거래소는 register_defaults()로 덮어쓰지 않음."""

    class CustomProvider(MockExchangeProvider):
        pass

    ExchangeProviderRegistry._registry[ExchangeType.UPBIT] = CustomProvider

    f = ExchangeProviderFactory.init(redis=redis_client)
    f.register_defaults()

    # UPBIT는 CustomProvider 유지
    assert ExchangeProviderRegistry.get(ExchangeType.UPBIT) is CustomProvider
    # 나머지는 MockProvider로 채워짐
    assert ExchangeProviderRegistry.get(ExchangeType.BINANCE) is MockExchangeProvider


# ── TC4: create() ─────────────────────────────────────────────────────────────


def test_factory_create_returns_provider(factory):
    """create()가 ExchangeProvider 인스턴스 반환."""
    from app.providers.base import ExchangeProvider

    provider = factory.create(
        exchange_type=ExchangeType.UPBIT,
        api_key="test-key",
        api_secret="test-secret",
        user_id="user-123",
    )
    assert isinstance(provider, ExchangeProvider)
    assert provider.exchange_type == ExchangeType.UPBIT


def test_factory_create_unregistered_raises(factory):
    """미등록 거래소 create() 시 KeyError."""
    ExchangeProviderRegistry._registry.clear()
    with pytest.raises(KeyError):
        factory.create(
            exchange_type=ExchangeType.UPBIT,
            api_key="key",
            api_secret="secret",
            user_id="user-123",
        )


def test_factory_create_tracks_active_providers(factory):
    """create() 후 _active_providers에 추가됨."""
    assert len(factory._active_providers) == 0
    factory.create(
        exchange_type=ExchangeType.UPBIT,
        api_key="k",
        api_secret="s",
        user_id="u",
    )
    assert len(factory._active_providers) == 1


# ── TC5: get_circuit_breaker() ────────────────────────────────────────────────


def test_get_circuit_breaker_returns_instance(factory):
    """get_circuit_breaker()가 거래소별 CircuitBreaker 반환."""
    from app.providers.circuit_breaker import CircuitBreaker
    from app.providers.enums import CircuitState

    cb = factory.get_circuit_breaker(ExchangeType.UPBIT)
    assert isinstance(cb, CircuitBreaker)
    assert cb.state == CircuitState.CLOSED


def test_circuit_breakers_are_per_exchange(factory):
    """거래소별로 독립된 CircuitBreaker 인스턴스."""
    cb_upbit = factory.get_circuit_breaker(ExchangeType.UPBIT)
    cb_binance = factory.get_circuit_breaker(ExchangeType.BINANCE)
    assert cb_upbit is not cb_binance


# ── TC6: Circuit Breaker 설정값 검증 ──────────────────────────────────────────


def test_circuit_breaker_all_exchanges_have_instance(factory):
    """모든 거래소에 CircuitBreaker 인스턴스 존재."""
    from app.providers.circuit_breaker import CircuitBreaker

    for exchange_type in ExchangeType:
        cb = factory.get_circuit_breaker(exchange_type)
        assert isinstance(cb, CircuitBreaker)


def test_circuit_breaker_config_from_settings(factory):
    """CircuitBreaker 설정이 settings 기반으로 생성됨."""
    from app.core.config import settings

    cb = factory.get_circuit_breaker(ExchangeType.UPBIT)
    assert cb._config.failure_threshold == settings.CB_FAILURE_THRESHOLD
    assert cb._config.failure_rate_threshold == settings.CB_FAILURE_RATE_THRESHOLD
    assert cb._config.recovery_timeout == settings.CB_RECOVERY_TIMEOUT
    assert cb._config.half_open_max_calls == 1


# ── TC7: close_all() ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_close_all_clears_providers(factory):
    """close_all() 후 _active_providers 비워지고 싱글턴 초기화."""
    factory.create(
        exchange_type=ExchangeType.UPBIT,
        api_key="k",
        api_secret="s",
        user_id="u",
    )
    assert len(factory._active_providers) == 1

    await factory.close_all()

    assert len(factory._active_providers) == 0
    assert ExchangeProviderFactory._instance is None
