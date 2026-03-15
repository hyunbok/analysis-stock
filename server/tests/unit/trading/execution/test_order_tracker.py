"""OrderTracker 단위 테스트 — 6건.

OrderRepository + ExchangeRestProvider AsyncMock으로 PG/거래소 의존성 격리.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from datetime import UTC, datetime

from app.providers.enums import OrderMethod, OrderSide, OrderStatus
from app.providers.types import OrderResult
from app.trading.execution.exceptions import OrderExecutionError
from app.trading.execution.order_tracker import OrderTracker


def _make_order_result(status: OrderStatus, qty: Decimal = Decimal("0.001")) -> OrderResult:
    return OrderResult(
        exchange_order_id="exc-order-001",
        market="KRW-BTC",
        side=OrderSide.BUY,
        method=OrderMethod.MARKET,
        status=status,
        quantity=qty,
        executed_quantity=qty,
        avg_executed_price=Decimal("100_000_000"),
        fee=Decimal("50"),
        fee_currency="KRW",
        created_at=datetime.now(UTC),
        executed_at=None,
    )


def _make_trade_order(exchange_order_id: str = "exc-order-001") -> MagicMock:
    order = MagicMock()
    order.id = uuid4()
    order.exchange_order_id = exchange_order_id
    order.status = "filled"
    order.executed_quantity = Decimal("0.001")
    order.executed_price = Decimal("100_000_000")
    order.fee = Decimal("50")
    return order


def _make_order_repo(trade_order: MagicMock) -> AsyncMock:
    repo = AsyncMock()
    repo.create.return_value = trade_order
    repo.update_status.return_value = None
    repo.update_after_execution.return_value = None
    repo.create_event.return_value = None
    repo.get_by_id.return_value = trade_order
    return repo


def _make_provider(result: OrderResult) -> AsyncMock:
    provider = AsyncMock()
    provider.place_order.return_value = result
    return provider


class TestCreateOrder:
    @pytest.mark.anyio
    async def test_success_returns_trade_order_and_result(self):
        """정상 주문 → (TradeOrder, OrderResult) 반환."""
        trade_order = _make_trade_order()
        order_result = _make_order_result(OrderStatus.FILLED)
        repo = _make_order_repo(trade_order)
        provider = _make_provider(order_result)

        tracker = OrderTracker(repo)
        returned_order, returned_result = await tracker.create_order(
            provider,
            user_id=uuid4(),
            exchange_account_id=uuid4(),
            coin_id=uuid4(),
            market="KRW-BTC",
            side=OrderSide.BUY,
            method=OrderMethod.MARKET,
            quantity=Decimal("0.001"),
            amount=Decimal("100_000"),
            price=None,
        )

        repo.create.assert_awaited_once()
        # ADR-18-2: is_ai_order=True 직접 설정 검증
        create_kwargs = repo.create.call_args.kwargs
        assert create_kwargs.get("is_ai_order") is True
        provider.place_order.assert_awaited_once()
        repo.update_after_execution.assert_awaited_once()
        assert returned_result.status == OrderStatus.FILLED

    @pytest.mark.anyio
    async def test_provider_failure_marks_db_failed_and_raises(self):
        """거래소 오류 → DB status=failed + OrderExecutionError raise."""
        trade_order = _make_trade_order()
        repo = _make_order_repo(trade_order)
        provider = AsyncMock()
        provider.place_order.side_effect = RuntimeError("거래소 연결 오류")

        tracker = OrderTracker(repo)
        with pytest.raises(OrderExecutionError):
            await tracker.create_order(
                provider,
                user_id=uuid4(),
                exchange_account_id=uuid4(),
                coin_id=uuid4(),
                market="KRW-BTC",
                side=OrderSide.BUY,
                method=OrderMethod.MARKET,
                quantity=Decimal("0.001"),
                amount=Decimal("100_000"),
                price=None,
            )
        repo.update_status.assert_awaited_once()
        repo.create_event.assert_awaited()


class TestWaitForFill:
    @pytest.mark.anyio
    async def test_no_exchange_order_id_returns_immediately(self):
        """exchange_order_id 없으면 즉시 반환."""
        trade_order = _make_trade_order(exchange_order_id=None)
        trade_order.exchange_order_id = None
        repo = _make_order_repo(trade_order)
        tracker = OrderTracker(repo)
        tracker.set_market("KRW-BTC")

        result = await tracker.wait_for_fill(AsyncMock(), trade_order)
        assert result is trade_order

    @pytest.mark.anyio
    async def test_polls_until_filled(self):
        """폴링 후 FILLED 상태 수신 시 즉시 반환."""
        trade_order = _make_trade_order()
        repo = _make_order_repo(trade_order)

        provider = AsyncMock()
        provider.get_order.return_value = _make_order_result(OrderStatus.FILLED)

        tracker = OrderTracker(repo)
        tracker.set_market("KRW-BTC")

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await tracker.wait_for_fill(provider, trade_order)

        provider.get_order.assert_awaited()
        repo.update_after_execution.assert_awaited()
        repo.create_event.assert_awaited()

    @pytest.mark.anyio
    async def test_timeout_cancels_remaining(self):
        """60초 경과 후 잔량 취소."""
        from app.trading.execution import constants
        original_wait = constants.PARTIAL_FILL_WAIT_SECONDS
        original_poll = constants.PARTIAL_FILL_POLL_INTERVAL

        # 테스트용: wait=20s, poll=10s → 2번 폴링 후 타임아웃
        trade_order = _make_trade_order()
        repo = _make_order_repo(trade_order)

        # 항상 PARTIAL 반환 → 타임아웃
        provider = AsyncMock()
        provider.get_order.return_value = _make_order_result(OrderStatus.PARTIAL)
        provider.cancel_order.return_value = True

        tracker = OrderTracker(repo)
        tracker.set_market("KRW-BTC")

        # PARTIAL_FILL_WAIT_SECONDS를 짧게 패치
        with (
            patch.object(constants, "PARTIAL_FILL_WAIT_SECONDS", 20),
            patch.object(constants, "PARTIAL_FILL_POLL_INTERVAL", 10),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            # order_tracker.py의 상수도 패치
            with (
                patch("app.trading.execution.order_tracker.PARTIAL_FILL_WAIT_SECONDS", 20),
                patch("app.trading.execution.order_tracker.PARTIAL_FILL_POLL_INTERVAL", 10),
            ):
                await tracker.wait_for_fill(provider, trade_order)

        provider.cancel_order.assert_awaited_once()
