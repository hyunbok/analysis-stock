"""Rate Limiter 통합 테스트 (fakeredis 사용)."""
from __future__ import annotations

import pytest
import pytest_asyncio
import fakeredis.aioredis as fakeredis

from app.core.rate_limiter import (
    APIRateLimiter,
    ExchangeRateLimiter,
    RateLimitConfig,
    TokenBucketRateLimiter,
)


@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


# ── TokenBucketRateLimiter Tests ──────────────────────────────────────────────

@pytest.mark.anyio
async def test_token_bucket_allows_first_request(redis_client):
    limiter = TokenBucketRateLimiter(redis_client)
    config = RateLimitConfig(max_tokens=10, refill_rate=1.0, window_ttl=60)
    result = await limiter.acquire("test:key:1", config)
    assert result.allowed is True
    assert result.remaining < 10  # 1 토큰 소비


@pytest.mark.anyio
async def test_token_bucket_exhaustion(redis_client):
    limiter = TokenBucketRateLimiter(redis_client)
    config = RateLimitConfig(max_tokens=3, refill_rate=0.01, window_ttl=60)

    results = [await limiter.acquire("test:exhaust", config) for _ in range(4)]
    assert all(r.allowed for r in results[:3])
    assert results[3].allowed is False
    assert results[3].retry_after_ms > 0


@pytest.mark.anyio
async def test_token_bucket_remaining_decreases(redis_client):
    limiter = TokenBucketRateLimiter(redis_client)
    config = RateLimitConfig(max_tokens=5, refill_rate=0.01, window_ttl=60)

    r1 = await limiter.acquire("test:decr", config)
    r2 = await limiter.acquire("test:decr", config)
    assert r2.remaining < r1.remaining


# ── APIRateLimiter Tests ──────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_api_rate_limiter_anon(redis_client):
    limiter = APIRateLimiter(redis_client)
    result = await limiter.check("192.168.1.1", authenticated=False)
    assert result.allowed is True


@pytest.mark.anyio
async def test_api_rate_limiter_auth(redis_client):
    limiter = APIRateLimiter(redis_client)
    result = await limiter.check("user-uuid-123", authenticated=True)
    assert result.allowed is True


@pytest.mark.anyio
async def test_login_rate_limiter(redis_client):
    limiter = APIRateLimiter(redis_client)
    results = [await limiter.check_login("10.0.0.1") for _ in range(6)]
    # 처음 5개는 허용, 6번째는 거부
    assert all(r.allowed for r in results[:5])
    assert results[5].allowed is False


# ── ExchangeRateLimiter Tests ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_exchange_rate_limiter_upbit_allows(redis_client):
    limiter = ExchangeRateLimiter(redis_client)
    result = await limiter.acquire("upbit", "user-1")
    assert result.allowed is True


@pytest.mark.anyio
async def test_exchange_rate_limiter_unknown_exchange(redis_client):
    limiter = ExchangeRateLimiter(redis_client)
    result = await limiter.acquire("unknown_exchange", "user-1")
    assert result.allowed is True  # 미등록 거래소는 통과


@pytest.mark.anyio
async def test_exchange_rate_limiter_per_second_exhaustion(redis_client):
    limiter = ExchangeRateLimiter(redis_client)
    # Upbit 초당 10회 제한 — 11번째는 거부
    results = []
    for _ in range(11):
        results.append(await limiter.acquire("upbit", "user-exhaust"))

    allowed_count = sum(1 for r in results if r.allowed)
    denied_count = sum(1 for r in results if not r.allowed)
    assert allowed_count == 10
    assert denied_count == 1
