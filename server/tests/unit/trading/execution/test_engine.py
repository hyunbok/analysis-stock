"""ExecutionEngine 단위 테스트 — 6건.

모든 의존성 Mock — DrawdownManager/RiskManager/OrderTracker/TradeLogger/Provider.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.providers.enums import OrderStatus
from app.providers.exceptions import ExchangeInsufficientBalanceError, ExchangeNetworkError
from app.trading.execution.drawdown_manager import DrawdownManager
from app.trading.execution.engine import ExecutionEngine
from app.trading.execution.exceptions import OrderExecutionError
from app.trading.execution.order_tracker import OrderTracker
from app.trading.execution.risk_manager import RiskManager
from app.trading.execution.trade_logger import TradeLogger
from app.trading.execution.types import (
    DrawdownState,
    PositionSizeResult,
    RiskCheckResult,
)

from .conftest import make_drawdown_state, make_execution_context, make_risk_params


def _make_risk_check(allowed: bool, reason: str = "OK") -> RiskCheckResult:
    return RiskCheckResult(
        allowed=allowed,
        reason=reason,
        daily_loss_ratio=0.0,
        mdd_ratio=0.0,
        consecutive_losses=0,
        active_position_count=0,
    )


def _make_position_size_result() -> PositionSizeResult:
    return PositionSizeResult(
        method="fixed_fractional",
        quantity=Decimal("0.001"),
        investment_amount=Decimal("100_000"),
        investment_ratio=0.01,
        stop_loss_ratio=0.03,
        kelly_fraction=None,
        strength_multiplier=1.0,
        position_scale=1.0,
        detail="FF test",
    )


def _make_trade_order() -> MagicMock:
    order = MagicMock()
    order.id = uuid4()
    order.exchange_order_id = "exc-001"
    order.status = "filled"
    order.executed_quantity = Decimal("0.001")
    order.executed_price = Decimal("100_000_000")
    order.fee = Decimal("50")
    return order


def _make_order_result(status=OrderStatus.FILLED):
    result = MagicMock()
    result.status = status
    result.exchange_order_id = "exc-001"
    result.executed_quantity = Decimal("0.001")
    result.avg_executed_price = Decimal("100_000_000")
    result.fee = Decimal("50")
    result.fee_currency = "KRW"
    result.executed_at = None
    return result


def _build_engine(
    *,
    drawdown_state: DrawdownState | None = None,
    active_count: int = 0,
    risk_allowed: bool = True,
    risk_reason: str = "OK",
    order_result=None,
    tracker_raises=None,
) -> ExecutionEngine:
    """테스트용 ExecutionEngine 조립."""
    # DrawdownManager mock
    dm = AsyncMock(spec=DrawdownManager)
    dm.get_state.return_value = drawdown_state or make_drawdown_state()
    dm.get_active_position_count.return_value = active_count
    dm.add_position.return_value = None

    # RiskManager mock (동기)
    rm = MagicMock(spec=RiskManager)
    rm.check.return_value = _make_risk_check(risk_allowed, risk_reason)

    # OrderTracker mock
    tracker = AsyncMock(spec=OrderTracker)
    if tracker_raises:
        tracker.create_order.side_effect = tracker_raises
    else:
        trade_order = _make_trade_order()
        ord_result = order_result or _make_order_result()
        tracker.create_order.return_value = (trade_order, ord_result)
    tracker.wait_for_fill.return_value = _make_trade_order()
    tracker.set_market.return_value = None

    # TradeLogger mock
    tl = AsyncMock(spec=TradeLogger)
    tl.log_entry.return_value = None

    # Provider mock
    provider = AsyncMock()
    provider.exchange_type = "upbit"

    return ExecutionEngine(
        risk_manager=rm,
        drawdown_manager=dm,
        order_tracker=tracker,
        trade_logger=tl,
        provider=provider,
    )


class TestRiskBlocked:
    @pytest.mark.anyio
    async def test_risk_check_failed_returns_skipped(self):
        """리스크 검증 실패 → status='skipped', skipped_reason 포함."""
        engine = _build_engine(
            risk_allowed=False,
            risk_reason="일일 손실 한도 초과",
        )
        context = make_execution_context()
        result = await engine.execute(context)

        assert result["status"] == "skipped"
        assert result["order_id"] is None
        assert "일일 손실" in result["skipped_reason"]

    @pytest.mark.anyio
    async def test_risk_check_passed_proceeds_to_order(self):
        """리스크 통과 → 주문 실행 진행, add_position 호출 확인."""
        engine = _build_engine(risk_allowed=True)
        context = make_execution_context()
        result = await engine.execute(context)

        assert result["status"] in ("filled", "partial", "open")
        assert result["order_id"] is not None
        # 파이프라인 8단계: 열린 포지션 등록
        engine._drawdown.add_position.assert_awaited_once()


class TestPositionSizingFailure:
    @pytest.mark.anyio
    async def test_insufficient_balance_returns_skipped(self):
        """잔고 부족 → PositionSizingError → status='skipped'."""
        from app.trading.execution.exceptions import PositionSizingError
        engine = _build_engine(risk_allowed=True)

        # 가용 잔고를 극도로 작게 설정
        context = make_execution_context(
            available_balance=Decimal("1"),  # 1원 — 최소 주문 5000원 미달
        )
        result = await engine.execute(context)

        assert result["status"] == "skipped"
        assert result["skipped_reason"] is not None


class TestNonRetryableError:
    @pytest.mark.anyio
    async def test_insufficient_balance_fails_immediately_without_retry(self):
        """ADR-18-7: 잔고 부족은 재시도 없이 즉시 status='failed' 반환.

        order_tracker.py가 모든 예외를 OrderExecutionError로 래핑하므로
        engine이 OrderExecutionError를 받아 status='failed' ExecutionResult 반환.
        OrderExecutionError는 _RETRYABLE_EXCEPTIONS에 없으므로 asyncio.sleep 미호출.
        """
        dm = AsyncMock(spec=DrawdownManager)
        dm.get_state.return_value = make_drawdown_state()
        dm.get_active_position_count.return_value = 0
        dm.add_position.return_value = None

        rm = MagicMock(spec=RiskManager)
        rm.check.return_value = _make_risk_check(True)

        tracker = AsyncMock(spec=OrderTracker)
        tracker.set_market.return_value = None
        # order_tracker.py:94의 실제 동작: 모든 거래소 예외를 OrderExecutionError로 래핑
        tracker.create_order.side_effect = OrderExecutionError(
            "잔고 부족",
            exchange_error=ExchangeInsufficientBalanceError("upbit", "잔고 부족"),
        )

        tl = AsyncMock(spec=TradeLogger)
        provider = AsyncMock()
        provider.exchange_type = "upbit"

        engine = ExecutionEngine(
            risk_manager=rm,
            drawdown_manager=dm,
            order_tracker=tracker,
            trade_logger=tl,
            provider=provider,
        )

        context = make_execution_context()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await engine.execute(context)

        # 재시도 없음: OrderExecutionError는 _RETRYABLE_EXCEPTIONS 아님
        mock_sleep.assert_not_awaited()
        # create_order 1회만 호출
        assert tracker.create_order.await_count == 1
        # engine이 failed ExecutionResult 반환
        assert result["status"] == "failed"


class TestRetryLogic:
    @pytest.mark.anyio
    async def test_retry_on_network_error_succeeds(self):
        """ExchangeNetworkError → 재시도 후 성공."""
        dm = AsyncMock(spec=DrawdownManager)
        dm.get_state.return_value = make_drawdown_state()
        dm.get_active_position_count.return_value = 0
        dm.add_position.return_value = None

        rm = MagicMock(spec=RiskManager)
        rm.check.return_value = _make_risk_check(True)

        trade_order = _make_trade_order()
        order_result = _make_order_result()
        call_count = 0

        tracker = AsyncMock(spec=OrderTracker)
        tracker.set_market.return_value = None
        tracker.wait_for_fill.return_value = trade_order

        async def create_order_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ExchangeNetworkError("upbit", "네트워크 오류")
            return (trade_order, order_result)

        tracker.create_order.side_effect = create_order_side_effect

        tl = AsyncMock(spec=TradeLogger)
        tl.log_entry.return_value = None
        provider = AsyncMock()
        provider.exchange_type = "upbit"

        engine = ExecutionEngine(
            risk_manager=rm,
            drawdown_manager=dm,
            order_tracker=tracker,
            trade_logger=tl,
            provider=provider,
        )

        context = make_execution_context()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.execute(context)

        assert call_count == 2
        assert result["status"] in ("filled", "partial", "open")

    @pytest.mark.anyio
    async def test_retry_exhausted_returns_failed(self):
        """재시도 모두 실패 → status='failed'."""
        dm = AsyncMock(spec=DrawdownManager)
        dm.get_state.return_value = make_drawdown_state()
        dm.get_active_position_count.return_value = 0
        dm.add_position.return_value = None

        rm = MagicMock(spec=RiskManager)
        rm.check.return_value = _make_risk_check(True)

        tracker = AsyncMock(spec=OrderTracker)
        tracker.set_market.return_value = None
        tracker.create_order.side_effect = ExchangeNetworkError("upbit", "지속 오류")

        tl = AsyncMock(spec=TradeLogger)
        provider = AsyncMock()
        provider.exchange_type = "upbit"

        engine = ExecutionEngine(
            risk_manager=rm,
            drawdown_manager=dm,
            order_tracker=tracker,
            trade_logger=tl,
            provider=provider,
        )

        context = make_execution_context()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.execute(context)

        assert result["status"] == "failed"
        assert result["order_id"] is None
