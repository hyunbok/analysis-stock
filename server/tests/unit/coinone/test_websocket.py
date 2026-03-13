"""_CoinOneWebSocketClient 단위 테스트 (7건)."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.coinone.stream import _CoinOneWebSocketClient
from app.providers.types import OrderBook, Ticker

# ── 헬퍼: 가짜 WebSocket ──────────────────────────────────────────────────────


def _make_fake_ws(messages: list[str] | None = None) -> MagicMock:
    """테스트용 가짜 WebSocket 객체 생성."""
    ws = MagicMock()
    ws.close_code = None
    ws.send = AsyncMock()
    ws.close = AsyncMock()

    _msgs = list(messages or [])

    async def fake_recv() -> str:
        if _msgs:
            return _msgs.pop(0)
        await asyncio.sleep(999)
        return ""

    ws.recv = fake_recv

    # async for 지원
    async def aiter(self: Any) -> AsyncIterator[str]:
        for m in list(_msgs):
            yield m

    ws.__aiter__ = aiter
    return ws


# ── 샘플 WS 메시지 ─────────────────────────────────────────────────────────────

_WS_TICKER_MSG = json.dumps({
    "response_type": "DATA",
    "channel": "TICKER",
    "data": {
        "quote_currency": "KRW",
        "target_currency": "BTC",
        "timestamp": 1710000000000,
        "last": "95000000",
        "first": "93000000",
        "high": "96000000",
        "low": "92000000",
        "target_volume": "100.5",
        "quote_volume": "9547500000",
    },
})

_WS_ORDERBOOK_MSG = json.dumps({
    "response_type": "DATA",
    "channel": "ORDERBOOK",
    "data": {
        "quote_currency": "KRW",
        "target_currency": "BTC",
        "timestamp": 1710000000000,
        "asks": [{"price": "95100000", "qty": "0.3"}],
        "bids": [{"price": "94900000", "qty": "0.5"}],
    },
})

_WS_PONG_MSG = json.dumps({"response_type": "PONG"})
_WS_ERROR_MSG = json.dumps({
    "response_type": "ERROR",
    "error_code": 4290,
    "message": "Too many connections",
})


# ── 테스트 ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_disconnect() -> None:
    """connect() 후 is_connected=True, disconnect() 후 is_connected=False."""
    client = _CoinOneWebSocketClient(reconnect_max=0)
    fake_ws = _make_fake_ws()

    with patch("websockets.connect", new=AsyncMock(return_value=fake_ws)):
        await client.connect()
        assert client.is_connected is True

        await client.disconnect()
        assert client.is_connected is False


@pytest.mark.asyncio
async def test_subscribe_sends_individual_messages() -> None:
    """구독 시 마켓별 개별 SUBSCRIBE 메시지 전송."""
    client = _CoinOneWebSocketClient(reconnect_max=0)
    fake_ws = _make_fake_ws()

    with patch("websockets.connect", new=AsyncMock(return_value=fake_ws)):
        await client.connect()
        await client.subscribe("TICKER", ["BTC", "ETH"], AsyncMock())

    # BTC, ETH 각각 SUBSCRIBE 전송 확인
    sent_messages = [json.loads(call.args[0]) for call in fake_ws.send.call_args_list]
    subscribe_msgs = [m for m in sent_messages if m.get("request_type") == "SUBSCRIBE"]

    assert len(subscribe_msgs) == 2
    targets = {m["topic"]["target_currency"] for m in subscribe_msgs}
    assert "BTC" in targets
    assert "ETH" in targets
    # channel 및 topic 형식 확인
    for msg in subscribe_msgs:
        assert msg["channel"] == "TICKER"
        assert msg["topic"]["quote_currency"] == "KRW"

    await client.disconnect()


@pytest.mark.asyncio
async def test_recv_ticker_callback() -> None:
    """TICKER 메시지 수신 시 mappers.parse_ticker → Ticker 콜백 호출."""
    received: list[Ticker] = []

    async def on_ticker(t: Ticker) -> None:
        received.append(t)

    client = _CoinOneWebSocketClient(reconnect_max=0)
    await client.subscribe("TICKER", ["BTC"], on_ticker)

    # _handle_message 직접 호출
    await client._handle_message(_WS_TICKER_MSG)

    assert len(received) == 1
    assert received[0].market == "BTC"
    assert received[0].price == Decimal("95000000")


@pytest.mark.asyncio
async def test_recv_orderbook_callback() -> None:
    """ORDERBOOK 메시지 수신 시 mappers.parse_orderbook → OrderBook 콜백 호출."""
    received: list[OrderBook] = []

    async def on_orderbook(ob: OrderBook) -> None:
        received.append(ob)

    client = _CoinOneWebSocketClient(reconnect_max=0)
    await client.subscribe("ORDERBOOK", ["BTC"], on_orderbook)

    await client._handle_message(_WS_ORDERBOOK_MSG)

    assert len(received) == 1
    assert received[0].market == "BTC"
    assert len(received[0].asks) == 1


@pytest.mark.asyncio
async def test_pong_ignored() -> None:
    """PONG 메시지 수신 시 콜백 호출 없이 무시."""
    callback = AsyncMock()
    client = _CoinOneWebSocketClient(reconnect_max=0)
    await client.subscribe("TICKER", ["BTC"], callback)

    await client._handle_message(_WS_PONG_MSG)

    callback.assert_not_called()


@pytest.mark.asyncio
async def test_reconnect_on_failure() -> None:
    """연결 실패 시 재연결 시도 (1회 실패 후 성공)."""
    import websockets.exceptions

    client = _CoinOneWebSocketClient(reconnect_max=2)
    call_count = 0

    async def fake_connect(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise websockets.exceptions.WebSocketException("initial failure")
        return _make_fake_ws()

    with patch("websockets.connect", side_effect=fake_connect):
        await client.connect()

    assert call_count == 2
    assert client.is_connected is True
    await client.disconnect()


@pytest.mark.asyncio
async def test_max_reconnect_raises_network_error() -> None:
    """최대 재연결 횟수 초과 시 ExchangeNetworkError raise."""
    import websockets.exceptions

    reconnect_max = 2
    client = _CoinOneWebSocketClient(reconnect_max=reconnect_max)
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


@pytest.mark.asyncio
async def test_ping_message_format() -> None:
    """_ping_loop가 {"request_type": "PING"} JSON 형식으로 전송."""
    client = _CoinOneWebSocketClient(reconnect_max=0, ping_interval=0.001)
    fake_ws = _make_fake_ws()
    fake_ws.closed = False  # _ping_loop 진입 조건

    client._ws = fake_ws
    client._connected = True

    task = asyncio.create_task(client._ping_loop())
    await asyncio.sleep(0.05)  # ping_interval(0.001)이 충분히 경과하도록 대기
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert fake_ws.send.called
    sent_msg = json.loads(fake_ws.send.call_args[0][0])
    assert sent_msg == {"request_type": "PING"}


@pytest.mark.asyncio
async def test_reconnect_exponential_backoff() -> None:
    """재연결 대기 시간: 1s → 2s → 4s 지수 백오프 확인."""
    import websockets.exceptions

    sleep_calls: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    client = _CoinOneWebSocketClient(reconnect_max=3)

    async def always_fail(*args: Any, **kwargs: Any) -> None:
        raise websockets.exceptions.WebSocketException("fail")

    with (
        patch("websockets.connect", side_effect=always_fail),
        patch("asyncio.sleep", side_effect=mock_sleep),
    ):
        from app.providers.exceptions import ExchangeNetworkError
        with pytest.raises(ExchangeNetworkError):
            await client.connect()

    # reconnect_max=3 → sleep 3회 (attempt 1, 2, 3)
    assert len(sleep_calls) == 3
    # delay = min(2**(attempt-1), 60) + jitter
    # attempt=1: base=1s, attempt=2: base=2s, attempt=3: base=4s
    assert sleep_calls[0] >= 1.0
    assert sleep_calls[1] >= 2.0
    assert sleep_calls[2] >= 4.0
