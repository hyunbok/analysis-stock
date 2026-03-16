"""PriceAlertMonitor 단위 테스트.

설계서: docs/tasks/v1-21-price-alert-system-plan.md §10
테스트: ticker 파싱 + 조건 판단 (~8건)
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws.price_alert_monitor import PriceAlertMonitor


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_monitor(price_alert_service: MagicMock | None = None) -> PriceAlertMonitor:
    svc = price_alert_service or AsyncMock()
    redis = AsyncMock()
    return PriceAlertMonitor(price_alert_service=svc, pubsub_redis=redis)


def _make_ticker_message(
    exchange: str = "upbit",
    market: str = "KRW-BTC",
    price: str = "85000000",
    use_trade_price: bool = False,
) -> dict:
    """Redis Pub/Sub ticker 메시지 형식 생성."""
    data_key = "trade_price" if use_trade_price else "price"
    return {
        "type": "pmessage",
        "channel": f"ch:ticker:{exchange}:{market}",
        "data": json.dumps({"data": {data_key: price}}),
    }


# ── _on_ticker 파싱 테스트 ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_on_ticker_parses_exchange_and_market() -> None:
    """채널에서 exchange, market 파싱 → process_ticker 호출."""
    svc = AsyncMock()
    monitor = _make_monitor(svc)
    msg = _make_ticker_message(exchange="upbit", market="KRW-BTC", price="85000000")

    await monitor._on_ticker(msg)

    svc.process_ticker.assert_called_once_with(
        "upbit", "KRW-BTC", Decimal("85000000")
    )


@pytest.mark.anyio
async def test_on_ticker_uses_trade_price_key_if_price_missing() -> None:
    """price 키 없으면 trade_price 키 사용."""
    svc = AsyncMock()
    monitor = _make_monitor(svc)
    msg = _make_ticker_message(
        exchange="coinone", market="KRW-ETH", price="3500000", use_trade_price=True
    )

    await monitor._on_ticker(msg)

    svc.process_ticker.assert_called_once_with(
        "coinone", "KRW-ETH", Decimal("3500000")
    )


@pytest.mark.anyio
async def test_on_ticker_no_price_field_skips_processing() -> None:
    """price / trade_price 모두 없음 → process_ticker 호출 안 함."""
    svc = AsyncMock()
    monitor = _make_monitor(svc)
    msg = {
        "type": "pmessage",
        "channel": "ch:ticker:upbit:KRW-BTC",
        "data": json.dumps({"data": {}}),  # 가격 없음
    }

    await monitor._on_ticker(msg)

    svc.process_ticker.assert_not_called()


@pytest.mark.anyio
async def test_on_ticker_invalid_json_does_not_raise_and_skips() -> None:
    """잘못된 JSON 데이터 → JSONDecodeError 무시 + process_ticker 미호출."""
    svc = AsyncMock()
    monitor = _make_monitor(svc)
    msg = {
        "type": "pmessage",
        "channel": "ch:ticker:upbit:KRW-BTC",
        "data": "not_valid_json{{{",
    }

    await monitor._on_ticker(msg)  # 예외 없이 완료되어야 함

    svc.process_ticker.assert_not_called()


# ── start / stop 테스트 ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_start_creates_asyncio_task() -> None:
    """start() → asyncio.Task 생성."""
    monitor = _make_monitor()

    # _subscribe_loop을 즉시 종료되는 코루틴으로 교체
    async def mock_loop():
        pass

    monitor._subscribe_loop = mock_loop

    await monitor.start()

    assert monitor._task is not None
    assert isinstance(monitor._task, asyncio.Task)
    # 정리
    monitor._task.cancel()
    try:
        await monitor._task
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.anyio
async def test_stop_cancels_task() -> None:
    """stop() → task.cancel() 호출 + CancelledError 무시."""

    async def mock_loop():
        await asyncio.sleep(100)

    monitor = _make_monitor()
    monitor._subscribe_loop = mock_loop
    await monitor.start()

    await monitor.stop()

    assert monitor._task.cancelled() or monitor._task.done()


@pytest.mark.anyio
async def test_stop_without_start_is_safe() -> None:
    """start() 없이 stop() 호출 → 에러 없음."""
    monitor = _make_monitor()

    # 예외 없이 완료되어야 함
    await monitor.stop()


# ── process_ticker 위임 테스트 ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_on_ticker_passes_decimal_price_to_service() -> None:
    """가격 문자열 → Decimal 변환 후 서비스에 전달."""
    svc = AsyncMock()
    monitor = _make_monitor(svc)
    msg = _make_ticker_message(price="85000000.12345678")

    await monitor._on_ticker(msg)

    args = svc.process_ticker.call_args
    exchange, market, price = args[0]
    assert isinstance(price, Decimal)
    assert price == Decimal("85000000.12345678")
