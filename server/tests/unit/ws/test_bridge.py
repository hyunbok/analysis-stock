"""ExchangeStreamBridge 단위 테스트 — 참조 카운팅 및 스트림 관리."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws.bridge import ExchangeStreamBridge, StreamState


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _mock_provider():
    provider = MagicMock()
    provider.exchange_type = MagicMock()
    provider.exchange_type.value = "upbit"
    provider.is_connected = True
    provider.initialize = AsyncMock()
    provider.connect = AsyncMock()
    provider.disconnect = AsyncMock()
    provider.close = AsyncMock()
    provider.subscribe_ticker = AsyncMock()
    provider.subscribe_orderbook = AsyncMock()
    provider.unsubscribe = AsyncMock()
    return provider


def _make_bridge():
    factory = MagicMock()
    publisher = MagicMock()
    publisher.publish_ticker = AsyncMock()
    publisher.publish_orderbook = AsyncMock()
    bridge = ExchangeStreamBridge(factory, publisher)
    return bridge, factory, publisher


# ── ensure_stream / release_stream ────────────────────────────────────────────


@pytest.mark.anyio
async def test_ensure_stream_creates_subscription(monkeypatch):
    bridge, factory, _ = _make_bridge()
    provider = _mock_provider()
    factory.create.return_value = provider

    with patch("app.ws.bridge.ExchangeStreamBridge._get_or_create_provider", AsyncMock(return_value=provider)):
        await bridge.ensure_stream("upbit", "KRW-BTC", "ticker")

    key = bridge._stream_key("upbit", "ticker", "KRW-BTC")
    assert key in bridge._streams
    assert bridge._streams[key].ref_count == 1
    provider.subscribe_ticker.assert_called_once()


@pytest.mark.anyio
async def test_ensure_stream_ref_counting():
    bridge, factory, _ = _make_bridge()
    provider = _mock_provider()

    with patch("app.ws.bridge.ExchangeStreamBridge._get_or_create_provider", AsyncMock(return_value=provider)):
        await bridge.ensure_stream("upbit", "KRW-BTC", "ticker")
        await bridge.ensure_stream("upbit", "KRW-BTC", "ticker")

    key = bridge._stream_key("upbit", "ticker", "KRW-BTC")
    assert bridge._streams[key].ref_count == 2
    # subscribe_ticker은 1회만 호출 (첫 구독 시)
    assert provider.subscribe_ticker.call_count == 1


@pytest.mark.anyio
async def test_release_stream_decrements_ref_count():
    bridge, factory, _ = _make_bridge()
    provider = _mock_provider()

    with patch("app.ws.bridge.ExchangeStreamBridge._get_or_create_provider", AsyncMock(return_value=provider)):
        await bridge.ensure_stream("upbit", "KRW-BTC", "ticker")
        await bridge.ensure_stream("upbit", "KRW-BTC", "ticker")
        await bridge.release_stream("upbit", "KRW-BTC", "ticker")

    key = bridge._stream_key("upbit", "ticker", "KRW-BTC")
    assert bridge._streams[key].ref_count == 1


@pytest.mark.anyio
async def test_release_stream_last_subscriber_unsubscribes():
    bridge, factory, _ = _make_bridge()
    provider = _mock_provider()

    with patch("app.ws.bridge.ExchangeStreamBridge._get_or_create_provider", AsyncMock(return_value=provider)):
        await bridge.ensure_stream("upbit", "KRW-BTC", "ticker")
        # _providers를 직접 설정하여 _clear_channel에서 조회 가능하게
        bridge._providers["upbit"] = provider
        await bridge.release_stream("upbit", "KRW-BTC", "ticker")

    key = bridge._stream_key("upbit", "ticker", "KRW-BTC")
    assert key not in bridge._streams
    provider.unsubscribe.assert_called_once()


@pytest.mark.anyio
async def test_release_stream_unknown_key_is_noop():
    bridge, _, _ = _make_bridge()
    # 예외 없이 처리되어야 함
    await bridge.release_stream("upbit", "KRW-BTC", "ticker")


@pytest.mark.anyio
async def test_ensure_multiple_markets_separate_keys():
    bridge, factory, _ = _make_bridge()
    provider = _mock_provider()

    with patch("app.ws.bridge.ExchangeStreamBridge._get_or_create_provider", AsyncMock(return_value=provider)):
        await bridge.ensure_stream("upbit", "KRW-BTC", "ticker")
        await bridge.ensure_stream("upbit", "KRW-ETH", "ticker")

    btc_key = bridge._stream_key("upbit", "ticker", "KRW-BTC")
    eth_key = bridge._stream_key("upbit", "ticker", "KRW-ETH")
    assert bridge._streams[btc_key].ref_count == 1
    assert bridge._streams[eth_key].ref_count == 1
    assert provider.subscribe_ticker.call_count == 2


# ── close_all ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_close_all_disconnects_all_providers():
    bridge, factory, _ = _make_bridge()
    provider1 = _mock_provider()
    provider2 = _mock_provider()
    bridge._providers["upbit"] = provider1
    bridge._providers["coinone"] = provider2

    await bridge.close_all()

    provider1.disconnect.assert_called_once()
    provider1.close.assert_called_once()
    provider2.disconnect.assert_called_once()
    provider2.close.assert_called_once()
    assert len(bridge._providers) == 0
    assert len(bridge._streams) == 0


# ── disconnect leak prevention ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_release_on_disconnect_clears_ref_count():
    """연결 끊김 시 release_stream 호출로 ref_count가 0으로 감소."""
    bridge, factory, _ = _make_bridge()
    provider = _mock_provider()

    with patch("app.ws.bridge.ExchangeStreamBridge._get_or_create_provider", AsyncMock(return_value=provider)):
        await bridge.ensure_stream("upbit", "KRW-BTC", "ticker")
        bridge._providers["upbit"] = provider

        # disconnect 시 release_stream 호출
        await bridge.release_stream("upbit", "KRW-BTC", "ticker")

    key = bridge._stream_key("upbit", "ticker", "KRW-BTC")
    assert key not in bridge._streams  # 완전 제거됨


@pytest.mark.anyio
async def test_ensure_stream_with_new_subscription_increments_once():
    """is_new=True 경우에만 ensure_stream이 호출되어야 함."""
    bridge, factory, _ = _make_bridge()
    provider = _mock_provider()

    with patch("app.ws.bridge.ExchangeStreamBridge._get_or_create_provider", AsyncMock(return_value=provider)):
        await bridge.ensure_stream("upbit", "KRW-BTC", "ticker")

    key = bridge._stream_key("upbit", "ticker", "KRW-BTC")
    # 정확히 1회 ensure_stream → ref_count == 1
    assert bridge._streams[key].ref_count == 1


# ── callbacks ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_on_ticker_publishes_to_redis():
    bridge, _, publisher = _make_bridge()

    from decimal import Decimal
    from datetime import datetime, timezone

    ticker = MagicMock()
    ticker.exchange = MagicMock()
    ticker.exchange.value = "upbit"
    ticker.market = "KRW-BTC"
    ticker.symbol = "BTC/KRW"
    ticker.price = Decimal("50000000")
    ticker.open_price = Decimal("49000000")
    ticker.high_price = Decimal("51000000")
    ticker.low_price = Decimal("48000000")
    ticker.volume = Decimal("100")
    ticker.trade_value = Decimal("5000000000")
    ticker.change_rate = Decimal("0.02")
    ticker.timestamp = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)

    await bridge._on_ticker(ticker)
    publisher.publish_ticker.assert_called_once()
    call_args = publisher.publish_ticker.call_args[0]
    assert call_args[0] == "upbit"
    assert call_args[1] == "KRW-BTC"
    data = call_args[2]
    assert data["symbol"] == "BTC/KRW"
    assert data["price"] == 50000000.0


@pytest.mark.anyio
async def test_on_orderbook_publishes_to_redis():
    bridge, _, publisher = _make_bridge()

    orderbook = MagicMock()
    orderbook.exchange = MagicMock()
    orderbook.exchange.value = "upbit"
    orderbook.market = "KRW-BTC"
    orderbook.symbol = "BTC/KRW"
    orderbook.asks = []
    orderbook.bids = []
    orderbook.timestamp = MagicMock()
    orderbook.timestamp.isoformat.return_value = "2026-03-14T12:00:00Z"

    await bridge._on_orderbook(orderbook)
    publisher.publish_orderbook.assert_called_once()
