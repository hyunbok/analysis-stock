"""Redis Pub/Sub 발행자(Publisher) — JSON 엔벨로프 래핑."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.core.redis_keys import PubSubChannel

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RedisPublisher:
    """Redis Pub/Sub 발행자 — 채널별 발행 메서드 제공"""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish_ticker(self, exchange: str, market: str, data: dict) -> int:
        channel = PubSubChannel.ticker(exchange, market)
        return await self._publish(channel, "ticker", data)

    async def publish_orderbook(self, exchange: str, market: str, data: dict) -> int:
        channel = PubSubChannel.orderbook(exchange, market)
        return await self._publish(channel, "orderbook", data)

    async def publish_ai_signal(self, user_id: str, data: dict) -> int:
        channel = PubSubChannel.ai_signal(user_id)
        return await self._publish(channel, "ai_signal", data)

    async def publish_notification(self, user_id: str, data: dict) -> int:
        channel = PubSubChannel.notification(user_id)
        return await self._publish(channel, "notification", data)

    async def publish_price_alert(self, user_id: str, data: dict) -> int:
        channel = PubSubChannel.price_alert(user_id)
        return await self._publish(channel, "price_alert", data)

    async def publish_trades(self, exchange: str, market: str, data: dict) -> int:
        channel = PubSubChannel.trades(exchange, market)
        return await self._publish(channel, "trades", data)

    async def publish_my_orders(self, user_id: str, data: dict) -> int:
        channel = PubSubChannel.my_orders(user_id)
        return await self._publish(channel, "my_orders", data)

    async def publish_system(self, data: dict) -> int:
        channel = PubSubChannel.system()
        return await self._publish(channel, "system", data)

    async def _publish(self, channel: str, msg_type: str, data: dict) -> int:
        """공통 엔벨로프 래핑 후 발행. 수신 구독자 수 반환."""
        envelope = {
            "type": msg_type,
            "channel": channel,
            "timestamp": _now_iso(),
            "data": data,
        }
        try:
            return await self._redis.publish(channel, json.dumps(envelope, ensure_ascii=False))
        except Exception:
            logger.exception("Redis publish failed: channel=%s type=%s", channel, msg_type)
            return 0
