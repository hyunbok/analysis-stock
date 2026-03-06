"""Redis Pub/Sub 통합 테스트 (fakeredis 사용)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
import fakeredis.aioredis as fakeredis

from app.core.pubsub import RedisPublisher
from app.core.redis_keys import PubSubChannel
from app.ws.subscribers import PubSubSubscriber


@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def publisher(redis_client):
    return RedisPublisher(redis_client)


# ── Publisher Tests ───────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_publish_ticker(redis_client, publisher):
    channel = PubSubChannel.ticker("upbit", "KRW-BTC")
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    ticker_data = {
        "exchange": "upbit",
        "market": "KRW-BTC",
        "price": 95000000,
        "change_rate": 0.023,
    }
    await publisher.publish_ticker("upbit", "KRW-BTC", ticker_data)

    # 구독 확인 메시지 + 실제 메시지
    messages = []
    async for msg in pubsub.listen():
        if msg["type"] == "message":
            messages.append(msg)
            break

    assert len(messages) == 1
    envelope = json.loads(messages[0]["data"])
    assert envelope["type"] == "ticker"
    assert envelope["channel"] == channel
    assert "timestamp" in envelope
    assert envelope["data"] == ticker_data

    await pubsub.aclose()


@pytest.mark.anyio
async def test_publish_ai_signal(redis_client, publisher):
    user_id = "user-abc-123"
    channel = PubSubChannel.ai_signal(user_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    signal_data = {"action": "buy", "confidence": 0.85, "market": "KRW-BTC"}
    await publisher.publish_ai_signal(user_id, signal_data)

    messages = []
    async for msg in pubsub.listen():
        if msg["type"] == "message":
            messages.append(msg)
            break

    envelope = json.loads(messages[0]["data"])
    assert envelope["type"] == "ai_signal"
    assert envelope["data"] == signal_data

    await pubsub.aclose()


@pytest.mark.anyio
async def test_publish_notification(redis_client, publisher):
    user_id = "user-notify-1"
    channel = PubSubChannel.notification(user_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    notif_data = {"notification_id": "oid-1", "title": "매매 체결", "unread_count": 3}
    await publisher.publish_notification(user_id, notif_data)

    messages = []
    async for msg in pubsub.listen():
        if msg["type"] == "message":
            messages.append(msg)
            break

    envelope = json.loads(messages[0]["data"])
    assert envelope["type"] == "notification"
    assert envelope["data"]["title"] == "매매 체결"

    await pubsub.aclose()


@pytest.mark.anyio
async def test_publish_system(redis_client, publisher):
    channel = PubSubChannel.system()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    sys_data = {"event": "maintenance", "message": "점검 예정", "severity": "info"}
    await publisher.publish_system(sys_data)

    messages = []
    async for msg in pubsub.listen():
        if msg["type"] == "message":
            messages.append(msg)
            break

    envelope = json.loads(messages[0]["data"])
    assert envelope["type"] == "system"
    assert envelope["channel"] == channel

    await pubsub.aclose()


@pytest.mark.anyio
async def test_publish_no_subscribers_returns_zero(redis_client, publisher):
    """구독자 없을 때 0 반환 (fire-and-forget 정상 동작)"""
    count = await publisher.publish_ticker("binance", "USDT-BTC", {"price": 95000})
    assert count == 0


@pytest.mark.anyio
async def test_envelope_format(redis_client, publisher):
    """엔벨로프 공통 포맷 검증"""
    channel = PubSubChannel.price_alert("user-pa-1")
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    await publisher.publish_price_alert("user-pa-1", {"alert_id": "a1", "coin": "BTC"})

    messages = []
    async for msg in pubsub.listen():
        if msg["type"] == "message":
            messages.append(msg)
            break

    envelope = json.loads(messages[0]["data"])
    assert set(envelope.keys()) >= {"type", "channel", "timestamp", "data"}
    assert envelope["timestamp"].endswith("Z")

    await pubsub.aclose()


@pytest.mark.anyio
async def test_publish_trades_and_my_orders(redis_client, publisher):
    """trades, my_orders 채널 발행 검증"""
    # trades 채널
    trades_channel = PubSubChannel.trades("upbit", "KRW-BTC")
    pubsub_trades = redis_client.pubsub()
    await pubsub_trades.subscribe(trades_channel)

    await publisher.publish_trades("upbit", "KRW-BTC", {"price": 95000000, "volume": 0.01})

    messages = []
    async for msg in pubsub_trades.listen():
        if msg["type"] == "message":
            messages.append(msg)
            break
    envelope = json.loads(messages[0]["data"])
    assert envelope["type"] == "trades"
    assert envelope["channel"] == trades_channel
    await pubsub_trades.aclose()

    # my_orders 채널
    orders_channel = PubSubChannel.my_orders("user-1")
    pubsub_orders = redis_client.pubsub()
    await pubsub_orders.subscribe(orders_channel)

    await publisher.publish_my_orders("user-1", {"order_id": "o-1", "status": "filled"})

    messages2 = []
    async for msg in pubsub_orders.listen():
        if msg["type"] == "message":
            messages2.append(msg)
            break
    envelope2 = json.loads(messages2[0]["data"])
    assert envelope2["type"] == "my_orders"
    assert envelope2["channel"] == orders_channel
    await pubsub_orders.aclose()


# ── PubSubSubscriber Tests ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def ws_hub():
    """Mock WSHub."""
    hub = MagicMock()
    hub.broadcast_to_channel = AsyncMock()
    return hub


@pytest.mark.anyio
async def test_subscriber_dispatches_to_ws_hub(redis_client, ws_hub):
    """PubSubSubscriber가 수신 메시지를 WSHub로 브로드캐스트하는지 검증."""
    subscriber = PubSubSubscriber(redis_client, ws_hub)
    await subscriber.subscribe_ticker("upbit", "KRW-BTC")

    channel = PubSubChannel.ticker("upbit", "KRW-BTC")
    message = {"type": "ticker", "channel": channel, "timestamp": "2026-03-06T10:00:00Z", "data": {}}

    # listen 루프를 백그라운드 태스크로 실행
    listen_task = asyncio.create_task(subscriber.listen())

    # 메시지 발행
    publisher = RedisPublisher(redis_client)
    await publisher.publish_ticker("upbit", "KRW-BTC", {"price": 95000000})

    # WS Hub 호출 대기
    for _ in range(20):
        await asyncio.sleep(0.05)
        if ws_hub.broadcast_to_channel.called:
            break

    listen_task.cancel()
    try:
        await listen_task
    except asyncio.CancelledError:
        pass

    await subscriber.close()
    ws_hub.broadcast_to_channel.assert_called_once()
    call_channel = ws_hub.broadcast_to_channel.call_args[0][0]
    assert call_channel == channel


@pytest.mark.anyio
async def test_subscriber_subscribe_user_channels(redis_client, ws_hub):
    """subscribe_user_channels가 ai_signal/notification/price_alert 구독하는지 검증."""
    subscriber = PubSubSubscriber(redis_client, ws_hub)
    user_id = "user-sub-1"
    await subscriber.subscribe_user_channels(user_id)

    expected = {
        PubSubChannel.ai_signal(user_id),
        PubSubChannel.notification(user_id),
        PubSubChannel.price_alert(user_id),
    }
    assert subscriber._subscribed_channels == expected
    await subscriber.close()


@pytest.mark.anyio
async def test_subscriber_unsubscribe(redis_client, ws_hub):
    """unsubscribe_ticker 후 채널 집합에서 제거되는지 검증."""
    subscriber = PubSubSubscriber(redis_client, ws_hub)
    await subscriber.subscribe_ticker("upbit", "KRW-BTC")
    assert PubSubChannel.ticker("upbit", "KRW-BTC") in subscriber._subscribed_channels

    await subscriber.unsubscribe_ticker("upbit", "KRW-BTC")
    assert PubSubChannel.ticker("upbit", "KRW-BTC") not in subscriber._subscribed_channels
    await subscriber.close()


@pytest.mark.anyio
async def test_subscriber_invalid_json_does_not_crash(redis_client, ws_hub):
    """잘못된 JSON 수신 시 크래시 없이 로깅만 하는지 검증."""
    subscriber = PubSubSubscriber(redis_client, ws_hub)
    # _dispatch 직접 호출로 JSON 오류 경로 테스트
    await subscriber._dispatch("ch:ticker:upbit:KRW-BTC", "NOT_VALID_JSON{{{")
    ws_hub.broadcast_to_channel.assert_not_called()
    await subscriber.close()
