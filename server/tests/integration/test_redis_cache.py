"""Redis 캐시 서비스 통합 테스트 (fakeredis 사용)."""
from __future__ import annotations

import pytest
import pytest_asyncio
import fakeredis.aioredis as fakeredis

from app.services.auth_cache_service import AuthCacheService
from app.services.market_cache_service import MarketCacheService
from app.core.pubsub import RedisPublisher
from app.services.ai_cache_service import AICacheService


@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def auth_cache(redis_client):
    return AuthCacheService(redis_client)


@pytest_asyncio.fixture
async def market_cache(redis_client):
    return MarketCacheService(redis_client)


@pytest_asyncio.fixture
async def ai_cache(redis_client):
    publisher = RedisPublisher(redis_client)
    return AICacheService(redis_client, publisher)


# ── Auth Cache Tests ──────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_refresh_token_store_and_get(auth_cache):
    await auth_cache.store_refresh_token("user-1", "client-1", "hash-abc")
    result = await auth_cache.get_refresh_token("user-1", "client-1")
    assert result == "hash-abc"


@pytest.mark.anyio
async def test_refresh_token_revoke(auth_cache):
    await auth_cache.store_refresh_token("user-1", "client-1", "hash-abc")
    await auth_cache.revoke_refresh_token("user-1", "client-1")
    result = await auth_cache.get_refresh_token("user-1", "client-1")
    assert result is None


@pytest.mark.anyio
async def test_list_sessions(auth_cache):
    await auth_cache.store_refresh_token("user-2", "client-A", "hash-1")
    await auth_cache.store_refresh_token("user-2", "client-B", "hash-2")
    sessions = await auth_cache.list_sessions("user-2")
    assert set(sessions) == {"client-A", "client-B"}


@pytest.mark.anyio
async def test_revoke_all_sessions(auth_cache):
    await auth_cache.store_refresh_token("user-3", "c1", "h1")
    await auth_cache.store_refresh_token("user-3", "c2", "h2")
    count = await auth_cache.revoke_all_sessions("user-3")
    assert count == 2
    assert await auth_cache.list_sessions("user-3") == []


@pytest.mark.anyio
async def test_email_verify_code(auth_cache):
    await auth_cache.store_email_verify_code("test@example.com", "123456")
    assert await auth_cache.verify_email_code("test@example.com", "123456") is True
    # 1회용 — 두 번째 검증은 실패
    assert await auth_cache.verify_email_code("test@example.com", "123456") is False


@pytest.mark.anyio
async def test_email_verify_wrong_code(auth_cache):
    await auth_cache.store_email_verify_code("test@example.com", "654321")
    assert await auth_cache.verify_email_code("test@example.com", "000000") is False


# ── Market Cache Tests ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_ticker_cache(market_cache):
    data = {"price": 95000000, "change_rate": 0.02}
    await market_cache.set_ticker("upbit", "KRW-BTC", data)
    result = await market_cache.get_ticker("upbit", "KRW-BTC")
    assert result == data


@pytest.mark.anyio
async def test_ticker_cache_miss(market_cache):
    result = await market_cache.get_ticker("upbit", "KRW-ETH")
    assert result is None


@pytest.mark.anyio
async def test_candles_cache(market_cache):
    candles = [{"open": 94000000, "close": 95000000}, {"open": 95000000, "close": 96000000}]
    await market_cache.set_candles("upbit", "KRW-BTC", "1m", 2, candles)
    result = await market_cache.get_candles("upbit", "KRW-BTC", "1m", 2)
    assert result == candles


@pytest.mark.anyio
async def test_indicators_short_timeframe(market_cache):
    data = {"rsi": 45.5, "macd": 0.003}
    await market_cache.set_indicators("upbit", "KRW-BTC", "1m", data)
    result = await market_cache.get_indicators("upbit", "KRW-BTC", "1m")
    assert result == data


@pytest.mark.anyio
async def test_indicators_long_timeframe(market_cache):
    data = {"rsi": 60.0, "bollinger_upper": 100000000}
    await market_cache.set_indicators("upbit", "KRW-BTC", "1h", data)
    result = await market_cache.get_indicators("upbit", "KRW-BTC", "1h")
    assert result == data


@pytest.mark.anyio
async def test_regime_cache(market_cache):
    data = {"regime": "bullish", "confidence": 0.8}
    await market_cache.set_regime("upbit", "KRW-BTC", data)
    result = await market_cache.get_regime("upbit", "KRW-BTC")
    assert result == data


# ── AI Cache Tests ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_ai_decision_cache(ai_cache):
    data = {"action": "buy", "confidence": 0.85, "market": "KRW-BTC"}
    await ai_cache.set_ai_decision("user-1", "KRW-BTC", data)
    result = await ai_cache.get_ai_decision("user-1", "KRW-BTC")
    assert result == data


@pytest.mark.anyio
async def test_news_sentiment_cache(ai_cache):
    data = {"coin": "BTC", "sentiment": "positive", "score": 0.72}
    await ai_cache.set_news_sentiment("BTC", data)
    result = await ai_cache.get_news_sentiment("BTC")
    assert result == data


@pytest.mark.anyio
async def test_last_run_set_and_get(ai_cache):
    await ai_cache.set_last_run("user-1", "BTC")
    result = await ai_cache.get_last_run("user-1", "BTC")
    assert result is not None
    assert "Z" in result  # ISO 형식 확인


@pytest.mark.anyio
async def test_unread_count(ai_cache):
    await ai_cache.update_unread_count("user-1", 5)
    assert await ai_cache.get_unread_count("user-1") == 5


@pytest.mark.anyio
async def test_increment_unread_count(ai_cache):
    await ai_cache.update_unread_count("user-1", 3)
    new_val = await ai_cache.increment_unread_count("user-1")
    assert new_val == 4


@pytest.mark.anyio
async def test_get_unread_count_default(ai_cache):
    result = await ai_cache.get_unread_count("nonexistent-user")
    assert result == 0
