"""Token Bucket 기반 Rate Limiter — Lua 스크립트 원자적 구현."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from redis.asyncio import Redis

from app.core.redis_keys import RedisKey, RedisTTL

logger = logging.getLogger(__name__)

_LUA_SCRIPT_PATH = Path(__file__).parent / "lua" / "token_bucket.lua"
try:
    _LUA_SCRIPT: str = _LUA_SCRIPT_PATH.read_text()
except FileNotFoundError as e:
    raise FileNotFoundError(
        f"Token Bucket Lua 스크립트를 찾을 수 없습니다: {_LUA_SCRIPT_PATH}"
    ) from e


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: float
    retry_after_ms: int


@dataclass
class RateLimitConfig:
    max_tokens: int
    refill_rate: float  # tokens/second
    window_ttl: int     # seconds


class TokenBucketRateLimiter:
    """단일 Token Bucket — Lua EVALSHA 기반 원자적 구현"""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._sha: str | None = None

    async def _get_sha(self) -> str:
        if self._sha is None:
            self._sha = await self._redis.script_load(_LUA_SCRIPT)
        return self._sha

    async def acquire(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        try:
            sha = await self._get_sha()
            now = time.time()
            result = await self._redis.evalsha(
                sha,
                1,
                key,
                config.max_tokens,
                config.refill_rate,
                now,
                1,
                config.window_ttl,
            )
            allowed, remaining, retry_after_ms = result
            return RateLimitResult(
                allowed=bool(int(allowed)),
                remaining=float(remaining),
                retry_after_ms=int(retry_after_ms),
            )
        except Exception:
            logger.exception("Rate limiter acquire failed for key=%s; allowing by default", key)
            return RateLimitResult(allowed=True, remaining=0.0, retry_after_ms=0)


# ── Exchange 정책 상수 ────────────────────────────────────────────────────────

_SECOND_BUCKET = "s"  # suffix for per-second bucket key
_MINUTE_BUCKET = "m"  # suffix for per-minute bucket key

_EXCHANGE_LIMITS: dict[str, tuple[RateLimitConfig, RateLimitConfig]] = {
    # (per-second config, per-minute config)
    "upbit": (
        RateLimitConfig(max_tokens=10, refill_rate=10.0, window_ttl=10),
        RateLimitConfig(max_tokens=600, refill_rate=10.0, window_ttl=RedisTTL.RATE_WINDOW),
    ),
    "coinone": (
        RateLimitConfig(max_tokens=10, refill_rate=10.0, window_ttl=10),
        RateLimitConfig(max_tokens=300, refill_rate=5.0, window_ttl=RedisTTL.RATE_WINDOW),
    ),
    "coinbase": (
        RateLimitConfig(max_tokens=10, refill_rate=10.0, window_ttl=10),
        RateLimitConfig(max_tokens=300, refill_rate=5.0, window_ttl=RedisTTL.RATE_WINDOW),
    ),
    "binance": (
        RateLimitConfig(max_tokens=20, refill_rate=20.0, window_ttl=10),
        RateLimitConfig(max_tokens=1200, refill_rate=20.0, window_ttl=RedisTTL.RATE_WINDOW),
    ),
}


class ExchangeRateLimiter:
    """거래소별 이중 Token Bucket Rate Limiter (초당 + 분당)"""

    EXCHANGE_LIMITS: dict[str, tuple[RateLimitConfig, RateLimitConfig]] = _EXCHANGE_LIMITS

    def __init__(self, redis: Redis) -> None:
        self._limiter = TokenBucketRateLimiter(redis)

    async def acquire(self, exchange: str, user_id: str) -> RateLimitResult:
        """초당/분당 두 버킷 모두 통과해야 허용."""
        configs = self.EXCHANGE_LIMITS.get(exchange)
        if configs is None:
            return RateLimitResult(allowed=True, remaining=0.0, retry_after_ms=0)

        sec_cfg, min_cfg = configs
        base_key = RedisKey.rate_exchange(exchange, user_id)

        sec_result = await self._limiter.acquire(f"{base_key}:{_SECOND_BUCKET}", sec_cfg)
        if not sec_result.allowed:
            return sec_result

        min_result = await self._limiter.acquire(f"{base_key}:{_MINUTE_BUCKET}", min_cfg)
        if not min_result.allowed:
            return min_result

        # 두 버킷 모두 허용 — remaining은 더 작은 값
        return RateLimitResult(
            allowed=True,
            remaining=min(sec_result.remaining, min_result.remaining),
            retry_after_ms=0,
        )

    async def get_status(self, exchange: str, user_id: str) -> dict[str, RateLimitResult]:
        """현재 남은 토큰 수 조회 (토큰 소비 없음).

        Redis GET으로 원시 JSON을 읽어 현재 시각 기준 리필 후 remaining을 계산한다.
        버킷이 없으면 full 상태로 반환.
        """
        configs = self.EXCHANGE_LIMITS.get(exchange)
        if configs is None:
            return {}

        sec_cfg, min_cfg = configs
        base_key = RedisKey.rate_exchange(exchange, user_id)

        async def _read(key: str, cfg: RateLimitConfig) -> RateLimitResult:
            raw = await self._limiter._redis.get(key)
            if raw is None:
                return RateLimitResult(
                    allowed=True, remaining=float(cfg.max_tokens), retry_after_ms=0
                )
            data = json.loads(raw)
            now = time.time()
            elapsed = now - data["last_refill"]
            tokens = min(float(cfg.max_tokens), data["tokens"] + elapsed * cfg.refill_rate)
            allowed = tokens >= 1.0
            retry_ms = (
                max(0, int((1.0 - tokens) / cfg.refill_rate * 1000)) if not allowed else 0
            )
            return RateLimitResult(allowed=allowed, remaining=tokens, retry_after_ms=retry_ms)

        return {
            "per_second": await _read(f"{base_key}:{_SECOND_BUCKET}", sec_cfg),
            "per_minute": await _read(f"{base_key}:{_MINUTE_BUCKET}", min_cfg),
        }


class APIRateLimiter:
    """API 전역 Rate Limiter (비인증 IP / 인증 사용자)"""

    _ANON_CONFIG = RateLimitConfig(
        max_tokens=60,
        refill_rate=1.0,       # 1 token/second → 60/min
        window_ttl=RedisTTL.RATE_WINDOW,
    )
    _AUTH_CONFIG = RateLimitConfig(
        max_tokens=120,
        refill_rate=2.0,       # 2 tokens/second → 120/min
        window_ttl=RedisTTL.RATE_WINDOW,
    )
    _LOGIN_CONFIG = RateLimitConfig(
        max_tokens=5,
        refill_rate=5 / (15 * 60),  # 5 tokens per 15 min
        window_ttl=RedisTTL.LOGIN_RATE,
    )

    def __init__(self, redis: Redis) -> None:
        self._limiter = TokenBucketRateLimiter(redis)

    async def check(self, identifier: str, authenticated: bool) -> RateLimitResult:
        """identifier: IP(비인증) 또는 user_id(인증)"""
        if authenticated:
            key = RedisKey.rate_api_user(identifier)
            config = self._AUTH_CONFIG
        else:
            key = RedisKey.rate_api_ip(identifier)
            config = self._ANON_CONFIG
        return await self._limiter.acquire(key, config)

    async def check_login(self, ip: str) -> RateLimitResult:
        """로그인 시도 brute-force 방지"""
        return await self._limiter.acquire(RedisKey.rate_login(ip), self._LOGIN_CONFIG)
