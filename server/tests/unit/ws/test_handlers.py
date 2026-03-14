"""핸들러 단위 테스트 — SubscribeHandler / UnsubscribeHandler / PingHandler."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.ws import WSPingRequest, WSSubscribeRequest, WSUnsubscribeRequest
from app.ws.handlers import PingHandler, SubscribeHandler, UnsubscribeHandler
from app.ws.hub import Connection, WSHub


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _mock_hub(user_id: str = "user-1", conn_id: str = "conn-1") -> WSHub:
    hub = MagicMock(spec=WSHub)
    conn = MagicMock(spec=Connection)
    conn.user_id = user_id
    conn.subscriptions = set()
    hub.get_connection.return_value = conn
    hub.subscribe.return_value = True
    hub.unsubscribe.return_value = True
    hub.send_to_connection = AsyncMock()
    hub.update_ping = MagicMock()
    return hub


def _mock_subscriber() -> MagicMock:
    sub = MagicMock()
    sub.subscribe_ticker = AsyncMock()
    sub.subscribe_orderbook = AsyncMock()
    sub.subscribe_trades = AsyncMock()
    sub.subscribe_my_orders = AsyncMock()
    sub.subscribe_user_channels = AsyncMock()
    sub.subscribe_system = AsyncMock()
    return sub


def _mock_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge.ensure_stream = AsyncMock()
    bridge.release_stream = AsyncMock()
    return bridge


# ── SubscribeHandler ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_subscribe_ticker_success():
    hub = _mock_hub()
    subscriber = _mock_subscriber()
    bridge = _mock_bridge()
    handler = SubscribeHandler(hub, subscriber, bridge)

    msg = WSSubscribeRequest(
        action="subscribe", channel="ticker", exchange="upbit", market="KRW-BTC"
    )
    with patch("app.ws.handlers.settings") as mock_settings:
        mock_settings.WS_MAX_SUBSCRIPTIONS_PER_CONN = 50
        await handler.handle("conn-1", msg)

    hub.subscribe.assert_called_once()
    subscriber.subscribe_ticker.assert_called_once_with("upbit", "KRW-BTC")
    bridge.ensure_stream.assert_called_once_with("upbit", "KRW-BTC", "ticker")
    # 성공 응답 전송 확인
    hub.send_to_connection.assert_called_once()
    response = hub.send_to_connection.call_args[0][1]
    assert response["action"] == "subscribed"
    assert response["channel"] == "ticker"


@pytest.mark.anyio
async def test_subscribe_my_orders_personal_channel():
    hub = _mock_hub()
    subscriber = _mock_subscriber()
    bridge = _mock_bridge()
    handler = SubscribeHandler(hub, subscriber, bridge)

    msg = WSSubscribeRequest(action="subscribe", channel="my-orders")
    with patch("app.ws.handlers.settings") as mock_settings:
        mock_settings.WS_MAX_SUBSCRIPTIONS_PER_CONN = 50
        await handler.handle("conn-1", msg)

    hub.subscribe.assert_called_once()
    subscriber.subscribe_my_orders.assert_called_once_with("user-1")
    bridge.ensure_stream.assert_not_called()  # 시장 채널 아님
    response = hub.send_to_connection.call_args[0][1]
    assert response["action"] == "subscribed"
    assert response["channel"] == "my-orders"


@pytest.mark.anyio
async def test_subscribe_system_channel():
    hub = _mock_hub()
    subscriber = _mock_subscriber()
    bridge = _mock_bridge()
    handler = SubscribeHandler(hub, subscriber, bridge)

    msg = WSSubscribeRequest(action="subscribe", channel="system")
    with patch("app.ws.handlers.settings") as mock_settings:
        mock_settings.WS_MAX_SUBSCRIPTIONS_PER_CONN = 50
        await handler.handle("conn-1", msg)

    subscriber.subscribe_system.assert_called_once()
    response = hub.send_to_connection.call_args[0][1]
    assert response["action"] == "subscribed"


@pytest.mark.anyio
async def test_subscribe_limit_exceeded_sends_error():
    hub = _mock_hub()
    conn = hub.get_connection("conn-1")
    # 구독 수 최대치로 설정
    conn.subscriptions = {f"ch:test:{i}" for i in range(50)}

    subscriber = _mock_subscriber()
    bridge = _mock_bridge()
    handler = SubscribeHandler(hub, subscriber, bridge)

    msg = WSSubscribeRequest(
        action="subscribe", channel="ticker", exchange="upbit", market="KRW-BTC"
    )
    with patch("app.ws.handlers.settings") as mock_settings:
        mock_settings.WS_MAX_SUBSCRIPTIONS_PER_CONN = 50
        await handler.handle("conn-1", msg)

    hub.subscribe.assert_not_called()
    response = hub.send_to_connection.call_args[0][1]
    assert response["code"] == "SUBSCRIPTION_LIMIT_EXCEEDED"


@pytest.mark.anyio
async def test_subscribe_bridge_failure_sends_error():
    hub = _mock_hub()
    subscriber = _mock_subscriber()
    bridge = _mock_bridge()
    bridge.ensure_stream = AsyncMock(side_effect=Exception("WS connection failed"))
    handler = SubscribeHandler(hub, subscriber, bridge)

    msg = WSSubscribeRequest(
        action="subscribe", channel="ticker", exchange="upbit", market="KRW-BTC"
    )
    with patch("app.ws.handlers.settings") as mock_settings:
        mock_settings.WS_MAX_SUBSCRIPTIONS_PER_CONN = 50
        await handler.handle("conn-1", msg)

    response = hub.send_to_connection.call_args[0][1]
    assert response["code"] == "EXCHANGE_UNAVAILABLE"
    hub.unsubscribe.assert_called_once()  # 롤백


@pytest.mark.anyio
async def test_subscribe_duplicate_does_not_call_ensure_stream_twice():
    """동일 채널 중복 subscribe 시 bridge.ensure_stream은 1회만 호출."""
    hub = _mock_hub()
    subscriber = _mock_subscriber()
    bridge = _mock_bridge()
    handler = SubscribeHandler(hub, subscriber, bridge)

    msg = WSSubscribeRequest(
        action="subscribe", channel="ticker", exchange="upbit", market="KRW-BTC"
    )
    with patch("app.ws.handlers.settings") as mock_settings:
        mock_settings.WS_MAX_SUBSCRIPTIONS_PER_CONN = 50
        # 첫 번째 구독 — subscribe returns True
        hub.subscribe.return_value = True
        await handler.handle("conn-1", msg)
        assert bridge.ensure_stream.call_count == 1

        # 두 번째 구독 — subscribe returns False (이미 구독 중)
        hub.subscribe.return_value = False
        await handler.handle("conn-1", msg)
        # ensure_stream은 여전히 1회 (추가 증가 없음)
        assert bridge.ensure_stream.call_count == 1


# ── UnsubscribeHandler ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_unsubscribe_ticker_success():
    hub = _mock_hub()
    subscriber = _mock_subscriber()
    bridge = _mock_bridge()
    handler = UnsubscribeHandler(hub, subscriber, bridge)

    msg = WSUnsubscribeRequest(
        action="unsubscribe", channel="ticker", exchange="upbit", market="KRW-BTC"
    )
    await handler.handle("conn-1", msg)

    hub.unsubscribe.assert_called_once()
    bridge.release_stream.assert_called_once_with("upbit", "KRW-BTC", "ticker")
    response = hub.send_to_connection.call_args[0][1]
    assert response["action"] == "unsubscribed"


@pytest.mark.anyio
async def test_unsubscribe_personal_channel_no_bridge():
    hub = _mock_hub()
    subscriber = _mock_subscriber()
    bridge = _mock_bridge()
    handler = UnsubscribeHandler(hub, subscriber, bridge)

    msg = WSUnsubscribeRequest(action="unsubscribe", channel="my-orders")
    await handler.handle("conn-1", msg)

    hub.unsubscribe.assert_called_once()
    bridge.release_stream.assert_not_called()


# ── PingHandler ───────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_ping_updates_last_ping_and_sends_pong():
    hub = _mock_hub()
    handler = PingHandler(hub)

    msg = WSPingRequest(action="ping")
    await handler.handle("conn-1", msg)

    hub.update_ping.assert_called_once_with("conn-1")
    hub.send_to_connection.assert_called_once()
    response = hub.send_to_connection.call_args[0][1]
    assert response["action"] == "pong"
    assert "timestamp" in response
