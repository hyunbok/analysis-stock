"""MessageRouter 단위 테스트 — action 기반 디스패치 검증."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws.router import MessageRouter


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_router():
    hub = MagicMock()
    hub.send_to_connection = AsyncMock()
    hub.get_connection = MagicMock(return_value=MagicMock(subscriptions=set()))

    subscriber = MagicMock()
    bridge = MagicMock()
    return MessageRouter(hub, subscriber, bridge), hub


# ── route dispatch ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_route_subscribe_dispatches_to_subscribe_handler():
    router, hub = _make_router()
    router._subscribe_handler.handle = AsyncMock()

    await router.route(
        "conn-1",
        {"action": "subscribe", "channel": "ticker", "exchange": "upbit", "market": "KRW-BTC"},
    )
    router._subscribe_handler.handle.assert_called_once()


@pytest.mark.anyio
async def test_route_unsubscribe_dispatches_to_unsubscribe_handler():
    router, hub = _make_router()
    router._unsubscribe_handler.handle = AsyncMock()

    await router.route(
        "conn-1",
        {"action": "unsubscribe", "channel": "ticker", "exchange": "upbit", "market": "KRW-BTC"},
    )
    router._unsubscribe_handler.handle.assert_called_once()


@pytest.mark.anyio
async def test_route_ping_dispatches_to_ping_handler():
    router, hub = _make_router()
    router._ping_handler.handle = AsyncMock()

    await router.route("conn-1", {"action": "ping"})
    router._ping_handler.handle.assert_called_once()


@pytest.mark.anyio
async def test_route_unknown_action_sends_error():
    router, hub = _make_router()

    # 판별 유니온에서 "foobar"는 Literal["subscribe"|"unsubscribe"|"ping"]에 없으므로
    # ValidationError → INVALID_MESSAGE 코드로 응답
    await router.route("conn-1", {"action": "foobar"})
    hub.send_to_connection.assert_called_once()
    call_args = hub.send_to_connection.call_args[0]
    assert call_args[1]["code"] == "INVALID_MESSAGE"


@pytest.mark.anyio
async def test_route_invalid_json_sends_error():
    router, hub = _make_router()

    # action 없음 → ValidationError
    await router.route("conn-1", {"foo": "bar"})
    hub.send_to_connection.assert_called_once()
    call_args = hub.send_to_connection.call_args[0]
    assert call_args[1]["code"] == "INVALID_MESSAGE"


@pytest.mark.anyio
async def test_route_missing_exchange_for_ticker_sends_error():
    router, hub = _make_router()

    # 시장 채널에 exchange/market 누락
    await router.route("conn-1", {"action": "subscribe", "channel": "ticker"})
    hub.send_to_connection.assert_called_once()
    call_args = hub.send_to_connection.call_args[0]
    assert call_args[1]["code"] == "INVALID_MESSAGE"


@pytest.mark.anyio
async def test_route_personal_channel_subscribe():
    router, hub = _make_router()
    router._subscribe_handler.handle = AsyncMock()

    await router.route("conn-1", {"action": "subscribe", "channel": "my-orders"})
    router._subscribe_handler.handle.assert_called_once()
