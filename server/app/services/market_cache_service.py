"""기술적 지표 및 시세 관련 Redis 캐시 서비스."""
from __future__ import annotations

import json
import logging

from redis.asyncio import Redis

from app.core.redis_keys import RedisKey, RedisTTL

logger = logging.getLogger(__name__)

_SHORT_TIMEFRAMES = {"1m", "3m", "5m"}


class MarketCacheService:
    """시세/캔들/지표/장세 캐시 관리"""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # ── Ticker ────────────────────────────────────────────────────────────────

    async def set_ticker(self, exchange: str, market: str, data: dict) -> None:
        await self._redis.set(
            RedisKey.ticker(exchange, market),
            json.dumps(data, ensure_ascii=False),
            ex=RedisTTL.TICKER,
        )

    async def get_ticker(self, exchange: str, market: str) -> dict | None:
        raw = await self._redis.get(RedisKey.ticker(exchange, market))
        return json.loads(raw) if raw else None

    # ── Candles ───────────────────────────────────────────────────────────────

    async def set_candles(
        self,
        exchange: str,
        market: str,
        timeframe: str,
        count: int,
        data: list[dict],
    ) -> None:
        await self._redis.set(
            RedisKey.candles(exchange, market, timeframe, count),
            json.dumps(data, ensure_ascii=False),
            ex=RedisTTL.CANDLES,
        )

    async def get_candles(
        self, exchange: str, market: str, timeframe: str, count: int
    ) -> list[dict] | None:
        raw = await self._redis.get(RedisKey.candles(exchange, market, timeframe, count))
        return json.loads(raw) if raw else None

    # ── Orderbook ─────────────────────────────────────────────────────────────

    async def set_orderbook(self, exchange: str, market: str, data: dict) -> None:
        await self._redis.set(
            RedisKey.orderbook(exchange, market),
            json.dumps(data, ensure_ascii=False),
            ex=RedisTTL.ORDERBOOK,
        )

    async def get_orderbook(self, exchange: str, market: str) -> dict | None:
        raw = await self._redis.get(RedisKey.orderbook(exchange, market))
        return json.loads(raw) if raw else None

    # ── Indicators ────────────────────────────────────────────────────────────

    async def set_indicators(
        self, exchange: str, market: str, timeframe: str, data: dict
    ) -> None:
        ttl = (
            RedisTTL.INDICATORS_SHORT
            if timeframe in _SHORT_TIMEFRAMES
            else RedisTTL.INDICATORS_LONG
        )
        await self._redis.set(
            RedisKey.indicators(exchange, market, timeframe),
            json.dumps(data, ensure_ascii=False),
            ex=ttl,
        )

    async def get_indicators(
        self, exchange: str, market: str, timeframe: str
    ) -> dict | None:
        raw = await self._redis.get(RedisKey.indicators(exchange, market, timeframe))
        return json.loads(raw) if raw else None

    # ── Regime ────────────────────────────────────────────────────────────────

    async def set_regime(self, exchange: str, market: str, data: dict) -> None:
        await self._redis.set(
            RedisKey.regime(exchange, market),
            json.dumps(data, ensure_ascii=False),
            ex=RedisTTL.REGIME,
        )

    async def get_regime(self, exchange: str, market: str) -> dict | None:
        raw = await self._redis.get(RedisKey.regime(exchange, market))
        return json.loads(raw) if raw else None
