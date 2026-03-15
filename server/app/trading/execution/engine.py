"""주문 실행 엔진 — 오케스트레이터.

TradingSignal → 리스크 검증 → 포지션 사이징 → 주문 실행 → 상태 추적 → 로깅.
OrderService를 import하지 않음 — Provider + AsyncSession 직접 주입.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from uuid import UUID

from app.providers.base import ExchangeRestProvider
from app.providers.enums import OrderMethod, OrderSide, OrderStatus
from app.providers.exceptions import ExchangeNetworkError, ExchangeUnavailableError

from .constants import MAX_RETRY_COUNT, RETRY_INTERVAL_SECONDS
from .drawdown_manager import DrawdownManager
from .exceptions import OrderExecutionError, PositionSizingError
from .order_tracker import OrderTracker
from .position_sizing import FixedFractionalSizer, HalfKellySizer
from .risk_manager import RiskManager
from .sl_tp import DynamicStopLoss
from .trade_logger import TradeLogger
from .types import (
    ExecutionResult,
    PositionSizeResult,
    RiskCheckResult,
    TradeExecutionContext,
)

logger = logging.getLogger(__name__)

_RETRYABLE_EXCEPTIONS = (
    ExchangeNetworkError,
    ExchangeUnavailableError,
)


class ExecutionEngine:
    """주문 실행 오케스트레이터.

    의존성 주입 (Celery task에서 직접 인스턴스화):
    - risk_manager: RiskManager (순수 계산)
    - drawdown_manager: DrawdownManager (Redis)
    - order_tracker: OrderTracker (OrderRepository)
    - trade_logger: TradeLogger (Beanie, 주입 없음)
    - provider: ExchangeRestProvider (거래소)

    Note:
      FixedFractionalSizer, HalfKellySizer는 @staticmethod이므로 주입 불필요.
      DynamicStopLoss도 @staticmethod이므로 주입 불필요.
    """

    def __init__(
        self,
        risk_manager: RiskManager,
        drawdown_manager: DrawdownManager,
        order_tracker: OrderTracker,
        trade_logger: TradeLogger,
        provider: ExchangeRestProvider,
    ) -> None:
        self._risk_manager = risk_manager
        self._drawdown = drawdown_manager
        self._tracker = order_tracker
        self._logger = trade_logger
        self._provider = provider

    async def execute(
        self,
        context: TradeExecutionContext,
    ) -> ExecutionResult:
        """TradingSignal → 주문 실행 전체 흐름.

        1. DrawdownManager.get_state() → 드로다운 상태 조회 (Redis)
        2. RiskManager.check() → 리스크 사전 검증 (순수)
        3. FixedFractionalSizer + HalfKellySizer → min 보수적 선택 (순수)
        4. DynamicStopLoss.calculate() → SL/TP 확정 (순수)
        5. OrderTracker.create_order() → 주문 생성 (PG + Provider)
        6. [partial 시] OrderTracker.wait_for_fill() → 부분 체결 대기
        7. DrawdownManager.add_position() → 열린 포지션 추가
        8. TradeLogger.log_entry() → MongoDB 기록
        9. 재시도: 30초 간격 최대 2회 (네트워크/가용성 오류만)
        """
        user_id = context["user_id"]
        exchange_account_id = context["exchange_account_id"]
        signal = context["signal"]
        risk_params = context["risk_params"]
        total_capital = context["total_capital"]
        available_balance = context["available_balance"]

        # 1. 드로다운 상태 조회
        drawdown_state = await self._drawdown.get_state(user_id, exchange_account_id)

        # 2. 동시 포지션 수 조회
        active_count = await self._drawdown.get_active_position_count(
            user_id, exchange_account_id
        )

        # 3. 리스크 검증
        risk_check = self._risk_manager.check(drawdown_state, risk_params, active_count)

        if not risk_check["allowed"]:
            logger.info(
                "trade skipped by risk check: %s (user=%s)",
                risk_check["reason"], user_id,
            )
            return ExecutionResult(
                order_id=None,
                exchange_order_id=None,
                status="skipped",
                quantity=Decimal("0"),
                executed_quantity=Decimal("0"),
                executed_price=None,
                fee=Decimal("0"),
                position_size=None,
                risk_check=risk_check,
                skipped_reason=risk_check["reason"],
                detail=f"리스크 검증 차단: {risk_check['reason']}",
            )

        # 4. 포지션 사이징 (FF + HK 중 보수적 선택)
        try:
            position_size = self._select_position_size(
                total_capital, available_balance, signal, risk_params
            )
        except PositionSizingError as exc:
            logger.warning("position sizing failed: %s", exc)
            return ExecutionResult(
                order_id=None,
                exchange_order_id=None,
                status="skipped",
                quantity=Decimal("0"),
                executed_quantity=Decimal("0"),
                executed_price=None,
                fee=Decimal("0"),
                position_size=None,
                risk_check=risk_check,
                skipped_reason=str(exc),
                detail=f"포지션 사이징 실패: {exc}",
            )

        # 5. SL/TP 계산
        exit_params = signal["exit_params"]
        # TODO: v2에서 TradingSignal에 atr 필드 추가 후 실제값 사용 (현재 entry_price × 1% 근사치)
        atr_val = exit_params.get("stop_loss_atr_mult", 1.5) * (
            signal["entry_price"] * 0.01
        )
        sl_params = DynamicStopLoss.calculate(
            entry_price=signal["entry_price"],
            stop_loss_price=exit_params["stop_loss"],
            take_profit_price=exit_params["take_profit"],
            atr=atr_val,
            stop_loss_atr_mult=exit_params.get("stop_loss_atr_mult", 1.5),
            take_profit_atr_mult=exit_params.get("take_profit_atr_mult", 2.0),
        )

        # 6. 주문 실행 (재시도 포함)
        try:
            trade_order, order_result = await self._execute_with_retry(
                context, position_size
            )
        except OrderExecutionError as exc:
            logger.error("order execution failed after retries: %s", exc)
            return ExecutionResult(
                order_id=None,
                exchange_order_id=None,
                status="failed",
                quantity=position_size["quantity"],
                executed_quantity=Decimal("0"),
                executed_price=None,
                fee=Decimal("0"),
                position_size=position_size,
                risk_check=risk_check,
                skipped_reason=exc.reason,
                detail=f"주문 실행 실패: {exc.reason}",
            )

        order_id_str = str(trade_order.id)

        # 7. 부분 체결 처리
        final_order = trade_order
        if order_result.status == OrderStatus.PARTIAL:
            logger.info("partial fill detected, waiting for fill: %s", trade_order.id)
            self._tracker.set_market(context["market"])
            final_order = await self._tracker.wait_for_fill(self._provider, trade_order)

        # 8. 열린 포지션 추가
        await self._drawdown.add_position(user_id, exchange_account_id, order_id_str)

        # 9. 거래 로그 기록 (fire-and-forget 스타일, 오류 격리)
        try:
            await self._logger.log_entry(
                trade_order_id=trade_order.id,
                signal=signal,
                position_size=position_size,
                user_id=UUID(user_id),
                coin_symbol=context["symbol"],
                market_code=context["market"],
                exchange_type=str(self._provider.exchange_type),
                order_type=signal["action"],
                entry_price=Decimal(str(signal["entry_price"])),
                quantity=position_size["quantity"],
                fee=Decimal(str(order_result.fee)),
            )
        except Exception as exc:
            logger.warning("trade_log insert failed (non-critical): %s", exc)

        final_status = final_order.status if final_order.status else order_result.status.value
        executed_qty = final_order.executed_quantity or order_result.executed_quantity
        executed_price = final_order.executed_price or order_result.avg_executed_price

        return ExecutionResult(
            order_id=order_id_str,
            exchange_order_id=order_result.exchange_order_id,
            status=final_status,
            quantity=position_size["quantity"],
            executed_quantity=executed_qty,
            executed_price=Decimal(str(executed_price)) if executed_price else None,
            fee=Decimal(str(final_order.fee or order_result.fee)),
            position_size=position_size,
            risk_check=risk_check,
            skipped_reason=None,
            detail=(
                f"주문 실행 완료: {signal['action']} {position_size['quantity']} "
                f"@ {signal['entry_price']} ({position_size['method']})"
            ),
        )

    def _select_position_size(
        self,
        total_capital: Decimal,
        available_balance: Decimal,
        signal: dict,
        risk_params: dict,
    ) -> PositionSizeResult:
        """FF + HK 중 보수적(작은) 결과 선택."""
        ff_result = FixedFractionalSizer.calculate(
            total_capital, available_balance, signal, risk_params
        )
        hk_result = HalfKellySizer.calculate(
            total_capital, available_balance, signal, risk_params
        )

        # PRD §7.5.1: 보수적 선택
        if ff_result["investment_amount"] <= hk_result["investment_amount"]:
            position_size = ff_result
        else:
            position_size = hk_result

        # 잔고 초과 검사
        if position_size["investment_amount"] > available_balance:
            raise PositionSizingError(
                f"잔고 부족: 필요 {float(position_size['investment_amount']):.0f} "
                f"> 가용 {float(available_balance):.0f}"
            )

        # 최소 주문 금액 검사 (거래소 최소값 5000 KRW)
        if position_size["investment_amount"] < Decimal("5000"):
            raise PositionSizingError(
                f"최소 주문 금액 미달: {float(position_size['investment_amount']):.0f} < 5000"
            )

        return position_size

    async def _execute_with_retry(
        self,
        context: TradeExecutionContext,
        position_size: PositionSizeResult,
    ) -> tuple:
        """주문 실행 + 재시도 (네트워크/가용성 오류만)."""
        for attempt in range(MAX_RETRY_COUNT + 1):
            try:
                return await self._place_and_track(context, position_size)
            except _RETRYABLE_EXCEPTIONS as exc:
                if attempt < MAX_RETRY_COUNT:
                    logger.warning(
                        "retry %d/%d for user=%s: %s",
                        attempt + 1, MAX_RETRY_COUNT, context["user_id"], exc,
                    )
                    await asyncio.sleep(RETRY_INTERVAL_SECONDS)
                else:
                    raise OrderExecutionError("재시도 초과", exchange_error=exc)

        raise OrderExecutionError("알 수 없는 오류")  # 이 코드는 도달 불가

    async def _place_and_track(
        self,
        context: TradeExecutionContext,
        position_size: PositionSizeResult,
    ) -> tuple:
        """단일 주문 실행 시도."""
        signal = context["signal"]
        action = signal["action"]
        side = OrderSide.BUY if action == "buy" else OrderSide.SELL

        return await self._tracker.create_order(
            self._provider,
            user_id=UUID(context["user_id"]),
            exchange_account_id=UUID(context["exchange_account_id"]),
            coin_id=UUID(context["coin_id"]),
            market=context["market"],
            side=side,
            method=OrderMethod.MARKET,
            quantity=position_size["quantity"],
            amount=position_size["investment_amount"],
            price=None,  # 시장가
        )
