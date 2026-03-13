"""_UpbitWebSocketClient 단위 테스트 (7건)."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.types import OrderBook, Ticker
from app.providers.upbit.stream import _UpbitWebSocketClient

# ── 헬퍼: 가짜 WebSocket ──────────────────────────────────────────────────────


def _make_fake_ws(messages: list[bytes | str] | None = None) -> MagicMock:
    """테스트용 가짜 WebSocket 객체 생성."""
    ws = MagicMock()
    ws.close_code = None
    ws.send = AsyncMock()
    ws.close = AsyncMock()

    _msgs = list(messages or [])

    async def fake_recv() -> bytes | str:
        if _msgs:
            return _msgs.pop(0)
        await asyncio.Event().wait()  # 블로킹 (태스크 취소 전까지)
        return b""

    ws.recv = fake_recv

    # async for 지원
    async def aiter(self: Any) -> AsyncIterator[bytes | str]:
        for m in list(_msgs):
            yield m

    ws.__aiter__ = aiter
    return ws


_WS_TICKER_MSG = json.dumps({
    "type": "ticker",
    "code": "KRW-BTC",
    "trade_price": 95000000,
    "opening_price": 93000000,
    "high_price": 96000000,
    "low_price": 92000000,
    "acc_trade_volume_24h": 100.5,
    "acc_trade_price_24h": 9547500000.0,
    "signed_change_rate": 0.0215,
    "trade_timestamp": 1710000000000,
}).encode()

_WS_ORDERBOOK_MSG = json.dumps({
    "type": "orderbook",
    "code": "KRW-BTC",
    "timestamp": 1710000000000,
    "orderbook_units": [
        {"ask_price": 95100000, "ask_size": 0.3, "bid_price": 94900000, "bid_size": 0.5},
    ],
}).encode()


# ── 테스트 ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_disconnect() -> None:
    """connect() 후 is_connected=True, disconnect() 후 is_connected=False."""
    client = _UpbitWebSocketClient(reconnect_max=0)
    fake_ws = _make_fake_ws()

    with patch("websockets.connect", new=AsyncMock(return_value=fake_ws)):
        await client.connect()
        assert client.is_connected is True

        await client.disconnect()
        assert client.is_connected is False


@pytest.mark.asyncio
async def test_subscribe_ticker_message_format() -> None:
    """구독 메시지에 ticket, type='ticker', is_only_realtime=True, format='DEFAULT' 포함."""
    client = _UpbitWebSocketClient(reconnect_max=0)
    fake_ws = _make_fake_ws()

    with patch("websockets.connect", new=AsyncMock(return_value=fake_ws)):
        await client.connect()
        await client.subscribe("ticker", ["KRW-BTC"], AsyncMock())

    # send 호출 중 구독 메시지 확인
    call_args_list = fake_ws.send.call_args_list
    # 마지막 send가 구독 메시지
    last_msg_str = call_args_list[-1].args[0]
    last_msg = json.loads(last_msg_str)

    assert last_msg[0]["ticket"]  # ticket 있음
    ticker_entry = next((e for e in last_msg if e.get("type") == "ticker"), None)
    assert ticker_entry is not None
    assert "KRW-BTC" in ticker_entry["codes"]
    assert ticker_entry.get("is_only_realtime") is True
    assert last_msg[-1] == {"format": "DEFAULT"}

    await client.disconnect()


@pytest.mark.asyncio
async def test_recv_ticker_callback() -> None:
    """ticker 메시지 수신 시 mappers.parse_ticker → Ticker 콜백 호출."""
    received: list[Ticker] = []

    async def on_ticker(t: Ticker) -> None:
        received.append(t)

    client = _UpbitWebSocketClient(reconnect_max=0)
    await client.subscribe("ticker", ["KRW-BTC"], on_ticker)

    # _handle_message 직접 호출
    await client._handle_message(_WS_TICKER_MSG)

    assert len(received) == 1
    assert received[0].market == "KRW-BTC"
    assert received[0].price == Decimal("95000000")


@pytest.mark.asyncio
async def test_recv_orderbook_callback() -> None:
    """orderbook 메시지 수신 시 mappers.parse_orderbook → OrderBook 콜백 호출."""
    received: list[OrderBook] = []

    async def on_orderbook(ob: OrderBook) -> None:
        received.append(ob)

    client = _UpbitWebSocketClient(reconnect_max=0)
    await client.subscribe("orderbook", ["KRW-BTC"], on_orderbook)

    await client._handle_message(_WS_ORDERBOOK_MSG)

    assert len(received) == 1
    assert received[0].market == "KRW-BTC"
    assert len(received[0].asks) == 1


@pytest.mark.asyncio
async def test_reconnect_on_close() -> None:
    """연결 끊김 시 _connect_with_retry 재호출 (1회 재연결 성공)."""
    import websockets.exceptions

    client = _UpbitWebSocketClient(reconnect_max=2)

    call_count = 0

    async def fake_connect(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise websockets.exceptions.WebSocketException("initial failure")
        return _make_fake_ws()

    with (
        patch("websockets.connect", side_effect=fake_connect),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        await client.connect()

    assert call_count == 2
    assert client.is_connected is True
    await client.disconnect()


@pytest.mark.asyncio
async def test_reconnect_exponential_backoff() -> None:
    """재연결 대기 시간이 1s, 2s, 4s 순으로 증가하는지 검증."""
    import websockets.exceptions

    client = _UpbitWebSocketClient(reconnect_max=3)
    sleep_durations: list[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_durations.append(duration)

    async def always_fail(*args: Any, **kwargs: Any) -> None:
        raise websockets.exceptions.WebSocketException("always fail")

    with (
        patch("websockets.connect", side_effect=always_fail),
        patch("asyncio.sleep", side_effect=fake_sleep),
    ):
        from app.providers.exceptions import ExchangeNetworkError
        with pytest.raises(ExchangeNetworkError):
            await client.connect()

    # 대기 시간이 1s, 2s, 4s 순서 (jitter 포함이므로 범위 체크)
    assert len(sleep_durations) == 3
    assert 1.0 <= sleep_durations[0] < 1.2
    assert 2.0 <= sleep_durations[1] < 2.3
    assert 4.0 <= sleep_durations[2] < 4.5


@pytest.mark.asyncio
async def test_max_reconnect_attempts() -> None:
    """최대 재연결 횟수(reconnect_max) 초과 시 ExchangeNetworkError raise."""
    import websockets.exceptions

    reconnect_max = 2
    client = _UpbitWebSocketClient(reconnect_max=reconnect_max)
    attempt_count = 0

    async def always_fail(*args: Any, **kwargs: Any) -> None:
        nonlocal attempt_count
        attempt_count += 1
        raise websockets.exceptions.WebSocketException("always fail")

    with (
        patch("websockets.connect", side_effect=always_fail),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        from app.providers.exceptions import ExchangeNetworkError
        with pytest.raises(ExchangeNetworkError):
            await client.connect()

    # reconnect_max + 1회 시도 (초기 + max 재시도)
    assert attempt_count == reconnect_max + 1
