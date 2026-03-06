"""Rate Limiter 통합 테스트 (fakeredis 사용)."""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import fakeredis.aioredis as fakeredis

from app.core.rate_limiter import (
    APIRateLimiter,
    ExchangeRateLimiter,
    RateLimitConfig,
    RateLimitResult,
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


@pytest.mark.anyio
async def test_exchange_rate_limiter_get_status_no_consume(redis_client):
    """get_status()가 토큰을 소비하지 않는지 검증."""
    limiter = ExchangeRateLimiter(redis_client)
    # 먼저 acquire로 몇 개 소비
    for _ in range(3):
        await limiter.acquire("upbit", "user-status")

    # get_status 호출 전 remaining 확인
    status_before = await limiter.get_status("upbit", "user-status")
    remaining_before = status_before["per_second"].remaining

    # get_status를 여러 번 호출해도 remaining 감소 없음
    for _ in range(3):
        await limiter.get_status("upbit", "user-status")

    status_after = await limiter.get_status("upbit", "user-status")
    remaining_after = status_after["per_second"].remaining

    # 시간 경과로 약간 리필될 수 있으므로 감소하지 않았음을 확인
    assert remaining_after >= remaining_before - 0.01  # 오차 허용


@pytest.mark.anyio
async def test_token_bucket_graceful_degradation_on_error(redis_client):
    """Redis 오류 시 graceful degradation — 요청 허용."""
    limiter = TokenBucketRateLimiter(redis_client)
    config = RateLimitConfig(max_tokens=10, refill_rate=1.0, window_ttl=60)

    # evalsha가 예외를 던지도록 모킹
    with patch.object(redis_client, "evalsha", side_effect=ConnectionError("Redis down")):
        with patch.object(redis_client, "script_load", new_callable=AsyncMock, return_value="sha"):
            result = await limiter.acquire("test:error", config)

    assert result.allowed is True  # 장애 시 허용
    assert result.remaining == 0.0
    assert result.retry_after_ms == 0


@pytest.mark.anyio
async def test_token_bucket_refill_over_time(redis_client):
    """시간 경과 후 토큰 리필 검증 (time.time 모킹)."""
    limiter = TokenBucketRateLimiter(redis_client)
    config = RateLimitConfig(max_tokens=10, refill_rate=10.0, window_ttl=60)
    key = "test:refill"

    fixed_time = 1000.0

    with patch("app.core.rate_limiter.time") as mock_time:
        mock_time.time.return_value = fixed_time
        # 10개 모두 소비
        for _ in range(10):
            await limiter.acquire(key, config)

        result_empty = await limiter.acquire(key, config)
        assert result_empty.allowed is False

        # 1초 후 → 10 tokens/sec × 1s = 10 tokens 리필
        mock_time.time.return_value = fixed_time + 1.0
        result_refilled = await limiter.acquire(key, config)
        assert result_refilled.allowed is True
