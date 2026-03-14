"""WebSocket 메시지 핸들러 — Subscribe / Unsubscribe / Ping."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.redis_keys import PubSubChannel
from app.schemas.ws import (
    MARKET_CHANNELS,
    WSChannel,
    WSPingRequest,
    WSPongMessage,
    WSSubscribedMessage,
    WSSubscribeRequest,
    WSUnsubscribedMessage,
    WSUnsubscribeRequest,
)
from app.ws.errors import WSErrors

if TYPE_CHECKING:
    from app.ws.bridge import ExchangeStreamBridge
    from app.ws.hub import WSHub
    from app.ws.subscribers import PubSubSubscriber

logger = logging.getLogger(__name__)


def _build_channel(
    user_id: str,
    msg: WSSubscribeRequest | WSUnsubscribeRequest,
) -> str:
    """채널 타입 + 파라미터 → Redis Pub/Sub 채널명 조립."""
    ch = msg.channel
    if ch == WSChannel.TICKER:
        return PubSubChannel.ticker(msg.exchange or "", msg.market or "")
    elif ch == WSChannel.ORDERBOOK:
        return PubSubChannel.orderbook(msg.exchange or "", msg.market or "")
    elif ch == WSChannel.TRADES:
        return PubSubChannel.trades(msg.exchange or "", msg.market or "")
    elif ch == WSChannel.MY_ORDERS:
        return PubSubChannel.my_orders(user_id)
    elif ch == WSChannel.AI_SIGNAL:
        return PubSubChannel.ai_signal(user_id)
    elif ch == WSChannel.NOTIFICATION:
        return PubSubChannel.notification(user_id)
    elif ch == WSChannel.PRICE_ALERT:
        return PubSubChannel.price_alert(user_id)
    elif ch == WSChannel.SYSTEM:
        return PubSubChannel.system()
    else:
        raise ValueError(f"Unknown channel: {ch}")


class SubscribeHandler:
    """채널 구독 요청 처리."""

    def __init__(
        self,
        hub: WSHub,
        subscriber: PubSubSubscriber,
        bridge: ExchangeStreamBridge,
    ) -> None:
        self._hub = hub
        self._subscriber = subscriber
        self._bridge = bridge

    async def handle(self, conn_id: str, msg: WSSubscribeRequest) -> None:
        conn = self._hub.get_connection(conn_id)
        if conn is None:
            return

        # 구독 한계 확인
        if len(conn.subscriptions) >= settings.WS_MAX_SUBSCRIPTIONS_PER_CONN:
            await self._hub.send_to_connection(conn_id, WSErrors.subscription_limit())
            return

        # 채널명 조립
        try:
            channel = _build_channel(conn.user_id, msg)
        except ValueError:
            await self._hub.send_to_connection(
                conn_id, WSErrors.invalid_channel(str(msg.channel))
            )
            return

        # Hub 구독 — 이미 구독 중이면 False (ref_count 이중 증가 방지)
        is_new = self._hub.subscribe(conn_id, channel)

        # Redis Pub/Sub 구독 (SUBSCRIBE는 멱등이므로 항상 호출)
        await self._subscribe_redis(conn.user_id, msg)

        # 거래소 스트림 시작 — 신규 구독 시에만 (is_new=True) ref_count 증가
        if is_new and msg.channel in MARKET_CHANNELS:
            try:
                await self._bridge.ensure_stream(
                    msg.exchange or "", msg.market or "", msg.channel.value
                )
            except Exception:
                logger.exception(
                    "ensure_stream failed exchange=%s market=%s channel=%s",
                    msg.exchange,
                    msg.market,
                    msg.channel,
                )
                await self._hub.send_to_connection(
                    conn_id, WSErrors.exchange_unavailable(msg.exchange or "")
                )
                self._hub.unsubscribe(conn_id, channel)
                return

        response = WSSubscribedMessage(
            channel=msg.channel.value,
            exchange=msg.exchange,
            market=msg.market,
        )
        await self._hub.send_to_connection(conn_id, response.model_dump(exclude_none=False))

    async def _subscribe_redis(self, user_id: str, msg: WSSubscribeRequest) -> None:
        """채널 타입별 Redis Pub/Sub 구독."""
        try:
            ch = msg.channel
            if ch == WSChannel.TICKER:
                await self._subscriber.subscribe_ticker(msg.exchange or "", msg.market or "")
            elif ch == WSChannel.ORDERBOOK:
                await self._subscriber.subscribe_orderbook(msg.exchange or "", msg.market or "")
            elif ch == WSChannel.TRADES:
                await self._subscriber.subscribe_trades(msg.exchange or "", msg.market or "")
            elif ch == WSChannel.MY_ORDERS:
                await self._subscriber.subscribe_my_orders(user_id)
            elif ch in (WSChannel.AI_SIGNAL, WSChannel.NOTIFICATION, WSChannel.PRICE_ALERT):
                await self._subscriber.subscribe_user_channels(user_id)
            elif ch == WSChannel.SYSTEM:
                await self._subscriber.subscribe_system()
        except Exception:
            logger.exception("Redis subscribe failed channel=%s", msg.channel)


class UnsubscribeHandler:
    """채널 구독 해제 요청 처리."""

    def __init__(
        self,
        hub: WSHub,
        subscriber: PubSubSubscriber,
        bridge: ExchangeStreamBridge,
    ) -> None:
        self._hub = hub
        self._subscriber = subscriber
        self._bridge = bridge

    async def handle(self, conn_id: str, msg: WSUnsubscribeRequest) -> None:
        conn = self._hub.get_connection(conn_id)
        if conn is None:
            return

        try:
            channel = _build_channel(conn.user_id, msg)
        except ValueError:
            await self._hub.send_to_connection(
                conn_id, WSErrors.invalid_channel(str(msg.channel))
            )
            return

        self._hub.unsubscribe(conn_id, channel)

        # 거래소 스트림 참조 카운트 감소
        if msg.channel in MARKET_CHANNELS:
            try:
                await self._bridge.release_stream(
                    msg.exchange or "", msg.market or "", msg.channel.value
                )
            except Exception:
                logger.exception(
                    "release_stream failed exchange=%s market=%s channel=%s",
                    msg.exchange,
                    msg.market,
                    msg.channel,
                )

        response = WSUnsubscribedMessage(
            channel=msg.channel.value,
            exchange=msg.exchange,
            market=msg.market,
        )
        await self._hub.send_to_connection(conn_id, response.model_dump(exclude_none=False))


class PingHandler:
    """클라이언트 Heartbeat ping 처리."""

    def __init__(self, hub: WSHub) -> None:
        self._hub = hub

    async def handle(self, conn_id: str, msg: WSPingRequest) -> None:
        self._hub.update_ping(conn_id)
        response = WSPongMessage()
        await self._hub.send_to_connection(conn_id, response.model_dump())
