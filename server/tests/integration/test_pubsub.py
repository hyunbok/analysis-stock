"""Redis Pub/Sub 통합 테스트 (fakeredis 사용)."""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
import fakeredis.aioredis as fakeredis

from app.core.pubsub import RedisPublisher
from app.core.redis_keys import PubSubChannel


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
