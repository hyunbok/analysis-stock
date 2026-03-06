"""Redis Pub/Sub → WebSocket 브리지 구독자."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.core.redis_keys import PubSubChannel

if TYPE_CHECKING:
    from app.ws.hub import WSHub

logger = logging.getLogger(__name__)


class PubSubSubscriber:
    """Redis Pub/Sub → WebSocket 브리지

    사용법:
        subscriber = PubSubSubscriber(redis, ws_hub)
        await subscriber.subscribe_ticker("upbit", "KRW-BTC")
        asyncio.create_task(subscriber.listen())
    """

    def __init__(self, redis: Redis, ws_hub: "WSHub") -> None:
        self._redis = redis
        self._hub = ws_hub
        self._pubsub: PubSub | None = None
        self._subscribed_channels: set[str] = set()
        self._running = False

    # ── Subscription management ───────────────────────────────────────────────

    async def subscribe_ticker(self, exchange: str, market: str) -> None:
        channel = PubSubChannel.ticker(exchange, market)
        await self._subscribe(channel)

    async def subscribe_user_channels(self, user_id: str) -> None:
        channels = [
            PubSubChannel.ai_signal(user_id),
            PubSubChannel.notification(user_id),
            PubSubChannel.price_alert(user_id),
        ]
        for channel in channels:
            await self._subscribe(channel)

    async def unsubscribe_ticker(self, exchange: str, market: str) -> None:
        channel = PubSubChannel.ticker(exchange, market)
        await self._unsubscribe(channel)

    async def unsubscribe_user_channels(self, user_id: str) -> None:
        channels = [
            PubSubChannel.ai_signal(user_id),
            PubSubChannel.notification(user_id),
            PubSubChannel.price_alert(user_id),
        ]
        for channel in channels:
            await self._unsubscribe(channel)

    # ── Listen loop ───────────────────────────────────────────────────────────

    async def listen(self) -> None:
        """메시지 수신 루프 — WS Hub로 전달. Exponential Backoff 재연결 포함."""
        self._running = True
        backoff = 0.5  # 초기 대기 0.5s
        while self._running:
            try:
                await self._ensure_pubsub()
                backoff = 0.5  # 성공 시 backoff 초기화
                async for raw in self._pubsub.listen():  # type: ignore[union-attr]
                    if not self._running:
                        break
                    if raw["type"] != "message":
                        continue
                    await self._dispatch(raw["channel"], raw["data"])
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "PubSubSubscriber listen error; reconnecting in %.1fs", backoff
                )
                # pubsub 재생성을 위해 초기화
                self._pubsub = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)  # cap 10s

    async def close(self) -> None:
        self._running = False
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.aclose()
            except Exception:
                logger.exception("Error closing PubSub connection")
            finally:
                self._pubsub = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _ensure_pubsub(self) -> None:
        if self._pubsub is None:
            self._pubsub = self._redis.pubsub()
            if self._subscribed_channels:
                await self._pubsub.subscribe(*self._subscribed_channels)

    async def _subscribe(self, channel: str) -> None:
        self._subscribed_channels.add(channel)
        await self._ensure_pubsub()
        try:
            await self._pubsub.subscribe(channel)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Failed to subscribe to channel=%s", channel)

    async def _unsubscribe(self, channel: str) -> None:
        self._subscribed_channels.discard(channel)
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe(channel)
            except Exception:
                logger.exception("Failed to unsubscribe from channel=%s", channel)

    async def _dispatch(self, channel: str, data: str) -> None:
        """수신 메시지를 파싱하여 WS Hub로 브로드캐스트."""
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from channel=%s: %s", channel, data[:200])
            return

        try:
            await self._hub.broadcast_to_channel(channel, message)
        except Exception:
            logger.exception("WS broadcast failed for channel=%s", channel)
