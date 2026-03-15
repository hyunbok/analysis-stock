"""실행 엔진 내부 예외.

trading/execution/ 패키지 전용. 서비스 레이어에서 catch 후 AppError로 변환.
providers/exceptions.py ↔ core/exceptions.py ExchangeErrors 패턴과 동일한 이중 레이어.
"""
from __future__ import annotations

from .types import DrawdownState


class TradeExecutionError(Exception):
    """실행 엔진 기본 예외."""


class RiskLimitExceeded(TradeExecutionError):
    """리스크 한도 초과 (daily_loss, mdd, consecutive_losses, max_positions).

    engine.py에서 catch하여 ExecutionResult(status="skipped") 반환.
    """

    def __init__(self, reason: str, state: DrawdownState) -> None:
        self.reason = reason
        self.state = state
        super().__init__(reason)


class PositionSizingError(TradeExecutionError):
    """포지션 사이징 실패 (잔고 부족, 최소 주문 미달 등)."""


class OrderExecutionError(TradeExecutionError):
    """주문 실행 실패 (거래소 오류 래핑)."""

    def __init__(self, reason: str, exchange_error: Exception | None = None) -> None:
        self.reason = reason
        self.exchange_error = exchange_error
        super().__init__(reason)
