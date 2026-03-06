"""AI 신호, 뉴스 감성, 알림 캐시 서비스."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.core.pubsub import RedisPublisher
from app.core.redis_keys import RedisKey, RedisTTL

logger = logging.getLogger(__name__)


class AICacheService:
    """AI 결정 / 뉴스 감성 / 알림 캐시 관리"""

    def __init__(self, redis: Redis, publisher: RedisPublisher) -> None:
        self._redis = redis
        self._publisher = publisher

    # ── AI Decision ───────────────────────────────────────────────────────────

    async def set_ai_decision(self, user_id: str, market: str, data: dict) -> None:
        """캐시 저장 + ai_signal Pub/Sub 발행"""
        await self._redis.set(
            RedisKey.ai_decision(user_id, market),
            json.dumps(data, ensure_ascii=False),
            ex=RedisTTL.AI_DECISION,
        )
        await self._publisher.publish_ai_signal(user_id, data)

    async def get_ai_decision(self, user_id: str, market: str) -> dict | None:
        raw = await self._redis.get(RedisKey.ai_decision(user_id, market))
        return json.loads(raw) if raw else None

    # ── News Sentiment ────────────────────────────────────────────────────────

    async def set_news_sentiment(self, coin: str, data: dict) -> None:
        await self._redis.set(
            RedisKey.news_sentiment(coin),
            json.dumps(data, ensure_ascii=False),
            ex=RedisTTL.NEWS_SENTIMENT,
        )

    async def get_news_sentiment(self, coin: str) -> dict | None:
        raw = await self._redis.get(RedisKey.news_sentiment(coin))
        return json.loads(raw) if raw else None

    # ── AI Last Run ───────────────────────────────────────────────────────────

    async def set_last_run(self, user_id: str, coin: str) -> None:
        """마지막 AI 분석 실행 시각을 현재 시각으로 저장"""
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        await self._redis.set(
            RedisKey.ai_last_run(user_id, coin),
            now_iso,
            ex=RedisTTL.AI_LAST_RUN,
        )

    async def get_last_run(self, user_id: str, coin: str) -> str | None:
        return await self._redis.get(RedisKey.ai_last_run(user_id, coin))

    # ── Unread Notification Count ─────────────────────────────────────────────

    async def update_unread_count(self, user_id: str, count: int) -> None:
        """미읽 알림 수 절대값 세팅"""
        await self._redis.set(
            RedisKey.unread_count(user_id),
            str(count),
            ex=RedisTTL.UNREAD_COUNT,
        )

    async def get_unread_count(self, user_id: str) -> int:
        raw = await self._redis.get(RedisKey.unread_count(user_id))
        return int(raw) if raw else 0

    async def increment_unread_count(self, user_id: str) -> int:
        """미읽 알림 수 1 증가. TTL이 없으면 새로 설정. 증가 후 값 반환."""
        key = RedisKey.unread_count(user_id)
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, RedisTTL.UNREAD_COUNT, xx=True)  # 기존 키만 expire 갱신
        results = await pipe.execute()
        new_value: int = results[0]
        # expire가 적용되지 않은 신규 키라면 TTL 설정
        if results[1] == 0:
            await self._redis.expire(key, RedisTTL.UNREAD_COUNT)
        return new_value
