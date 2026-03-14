"""WSHub 단위 테스트 — 연결 관리, 구독, 브로드캐스트, Heartbeat."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws.hub import Connection, WSHub


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _mock_websocket() -> MagicMock:
    ws = MagicMock()
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def hub() -> WSHub:
    return WSHub()


@pytest.fixture
def ws():
    return _mock_websocket()


# ── connect / disconnect ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_connect_returns_conn_id(hub: WSHub, ws: MagicMock):
    conn_id = await hub.connect(ws, "user-1")
    assert conn_id is not None
    assert hub.get_connection_count() == 1


@pytest.mark.anyio
async def test_connect_max_connections_returns_none(hub: WSHub):
    from app.ws import hub as hub_module
    original_max = hub_module.settings.WS_MAX_CONNECTIONS
    original_per_user = hub_module.settings.WS_MAX_CONNECTIONS_PER_USER
    try:
        hub_module.settings.WS_MAX_CONNECTIONS = 1
        hub_module.settings.WS_MAX_CONNECTIONS_PER_USER = 5
        ws1 = _mock_websocket()
        ws2 = _mock_websocket()
        conn_id1 = await hub.connect(ws1, "user-1")
        conn_id2 = await hub.connect(ws2, "user-2")
        assert conn_id1 is not None
        assert conn_id2 is None
    finally:
        hub_module.settings.WS_MAX_CONNECTIONS = original_max
        hub_module.settings.WS_MAX_CONNECTIONS_PER_USER = original_per_user


@pytest.mark.anyio
async def test_connect_max_per_user_returns_none(hub: WSHub):
    from app.ws import hub as hub_module
    original_max = hub_module.settings.WS_MAX_CONNECTIONS
    original_per_user = hub_module.settings.WS_MAX_CONNECTIONS_PER_USER
    try:
        hub_module.settings.WS_MAX_CONNECTIONS = 1000
        hub_module.settings.WS_MAX_CONNECTIONS_PER_USER = 2
        ws1 = _mock_websocket()
        ws2 = _mock_websocket()
        ws3 = _mock_websocket()
        await hub.connect(ws1, "user-1")
        await hub.connect(ws2, "user-1")
        result = await hub.connect(ws3, "user-1")
        assert result is None
    finally:
        hub_module.settings.WS_MAX_CONNECTIONS = original_max
        hub_module.settings.WS_MAX_CONNECTIONS_PER_USER = original_per_user


@pytest.mark.anyio
async def test_disconnect_removes_connection(hub: WSHub, ws: MagicMock):
    conn_id = await hub.connect(ws, "user-1")
    await hub.disconnect(conn_id)
    assert hub.get_connection_count() == 0
    assert hub.get_connection(conn_id) is None


@pytest.mark.anyio
async def test_disconnect_cleans_user_index(hub: WSHub):
    ws1, ws2 = _mock_websocket(), _mock_websocket()
    conn1 = await hub.connect(ws1, "user-1")
    conn2 = await hub.connect(ws2, "user-1")
    await hub.disconnect(conn1)
    # user-1 여전히 conn2 보유
    assert hub.get_connection(conn2) is not None
    await hub.disconnect(conn2)
    # 모든 연결 해제 후 user 인덱스도 제거
    assert hub.get_connection_count() == 0


@pytest.mark.anyio
async def test_disconnect_cleans_channel_subscriptions(hub: WSHub, ws: MagicMock):
    conn_id = await hub.connect(ws, "user-1")
    hub.subscribe(conn_id, "ch:ticker:upbit:KRW-BTC")
    assert hub.get_channel_subscriber_count("ch:ticker:upbit:KRW-BTC") == 1
    await hub.disconnect(conn_id)
    assert hub.get_channel_subscriber_count("ch:ticker:upbit:KRW-BTC") == 0


# ── subscribe / unsubscribe ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_subscribe_returns_true(hub: WSHub, ws: MagicMock):
    conn_id = await hub.connect(ws, "user-1")
    result = hub.subscribe(conn_id, "ch:ticker:upbit:KRW-BTC")
    assert result is True
    assert "ch:ticker:upbit:KRW-BTC" in hub.get_subscriptions(conn_id)


@pytest.mark.anyio
async def test_subscribe_duplicate_returns_false(hub: WSHub, ws: MagicMock):
    conn_id = await hub.connect(ws, "user-1")
    hub.subscribe(conn_id, "ch:ticker:upbit:KRW-BTC")
    result = hub.subscribe(conn_id, "ch:ticker:upbit:KRW-BTC")
    assert result is False
    assert hub.get_channel_subscriber_count("ch:ticker:upbit:KRW-BTC") == 1


@pytest.mark.anyio
async def test_subscribe_unknown_conn_returns_false(hub: WSHub):
    result = hub.subscribe("nonexistent", "ch:ticker:upbit:KRW-BTC")
    assert result is False


@pytest.mark.anyio
async def test_unsubscribe_removes_subscription(hub: WSHub, ws: MagicMock):
    conn_id = await hub.connect(ws, "user-1")
    hub.subscribe(conn_id, "ch:ticker:upbit:KRW-BTC")
    result = hub.unsubscribe(conn_id, "ch:ticker:upbit:KRW-BTC")
    assert result is True
    assert hub.get_channel_subscriber_count("ch:ticker:upbit:KRW-BTC") == 0


@pytest.mark.anyio
async def test_unsubscribe_not_subscribed_returns_false(hub: WSHub, ws: MagicMock):
    conn_id = await hub.connect(ws, "user-1")
    result = hub.unsubscribe(conn_id, "ch:ticker:upbit:KRW-BTC")
    assert result is False


# ── broadcast / send ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_broadcast_to_channel_sends_to_all_subscribers(hub: WSHub):
    ws1, ws2, ws3 = _mock_websocket(), _mock_websocket(), _mock_websocket()
    conn1 = await hub.connect(ws1, "user-1")
    conn2 = await hub.connect(ws2, "user-2")
    conn3 = await hub.connect(ws3, "user-3")

    hub.subscribe(conn1, "ch:ticker:upbit:KRW-BTC")
    hub.subscribe(conn2, "ch:ticker:upbit:KRW-BTC")
    # conn3은 다른 채널

    count = await hub.broadcast_to_channel(
        "ch:ticker:upbit:KRW-BTC", {"type": "ticker", "price": 50000}
    )
    assert count == 2
    ws1.send_text.assert_called_once()
    ws2.send_text.assert_called_once()
    ws3.send_text.assert_not_called()


@pytest.mark.anyio
async def test_broadcast_empty_channel_returns_zero(hub: WSHub):
    count = await hub.broadcast_to_channel("ch:ticker:upbit:KRW-BTC", {})
    assert count == 0


@pytest.mark.anyio
async def test_send_to_user_sends_to_all_user_connections(hub: WSHub):
    ws1, ws2 = _mock_websocket(), _mock_websocket()
    await hub.connect(ws1, "user-1")
    await hub.connect(ws2, "user-1")

    count = await hub.send_to_user("user-1", {"action": "test"})
    assert count == 2
    ws1.send_text.assert_called_once()
    ws2.send_text.assert_called_once()


@pytest.mark.anyio
async def test_send_to_connection(hub: WSHub, ws: MagicMock):
    conn_id = await hub.connect(ws, "user-1")
    result = await hub.send_to_connection(conn_id, {"action": "pong"})
    assert result is True
    ws.send_text.assert_called_once()


@pytest.mark.anyio
async def test_send_to_connection_unknown_returns_false(hub: WSHub):
    result = await hub.send_to_connection("nonexistent", {"action": "pong"})
    assert result is False


@pytest.mark.anyio
async def test_broadcast_json_serialized_once(hub: WSHub):
    """JSON 직렬화가 1회만 발생하는지 확인 (send_text 호출값 검증)."""
    ws1, ws2 = _mock_websocket(), _mock_websocket()
    conn1 = await hub.connect(ws1, "user-1")
    conn2 = await hub.connect(ws2, "user-2")
    hub.subscribe(conn1, "ch:ticker:upbit:KRW-BTC")
    hub.subscribe(conn2, "ch:ticker:upbit:KRW-BTC")

    msg = {"type": "ticker", "price": 50000}
    await hub.broadcast_to_channel("ch:ticker:upbit:KRW-BTC", msg)

    # 두 연결에 동일한 페이로드가 전달되어야 함
    payload1 = ws1.send_text.call_args[0][0]
    payload2 = ws2.send_text.call_args[0][0]
    assert payload1 == payload2


# ── update_ping / heartbeat ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_update_ping_updates_last_ping(hub: WSHub, ws: MagicMock):
    conn_id = await hub.connect(ws, "user-1")
    conn = hub.get_connection(conn_id)
    old_ping = conn.last_ping
    hub.update_ping(conn_id)
    assert conn.last_ping >= old_ping


@pytest.mark.anyio
async def test_heartbeat_disconnects_stale_connections(hub: WSHub):
    from app.ws import hub as hub_module
    ws = _mock_websocket()
    conn_id = await hub.connect(ws, "user-1")
    conn = hub.get_connection(conn_id)

    # last_ping을 70초 전으로 설정
    conn.last_ping = datetime.now(timezone.utc) - timedelta(seconds=70)

    original_timeout = hub_module.settings.WS_HEARTBEAT_TIMEOUT
    try:
        hub_module.settings.WS_HEARTBEAT_TIMEOUT = 60
        await hub._check_heartbeats()
    finally:
        hub_module.settings.WS_HEARTBEAT_TIMEOUT = original_timeout

    assert hub.get_connection(conn_id) is None


@pytest.mark.anyio
async def test_heartbeat_keeps_active_connections(hub: WSHub):
    from app.ws import hub as hub_module
    ws = _mock_websocket()
    conn_id = await hub.connect(ws, "user-1")

    original_timeout = hub_module.settings.WS_HEARTBEAT_TIMEOUT
    try:
        hub_module.settings.WS_HEARTBEAT_TIMEOUT = 60
        await hub._check_heartbeats()
    finally:
        hub_module.settings.WS_HEARTBEAT_TIMEOUT = original_timeout

    assert hub.get_connection(conn_id) is not None
