"""주문 실행 및 리스크 관리 엔진.

v1-15~17과 달리 순수 계산 패키지가 아님.
Redis(드로다운 상태), MongoDB(거래 로그), ExchangeProvider(주문)에 의존.
서비스 레이어(services/)에서 ExecutionEngine만 진입점으로 사용.
"""
from __future__ import annotations

from .engine import ExecutionEngine
from .types import (
    DrawdownState,
    ExecutionResult,
    PositionSizeResult,
    RiskCheckResult,
    RiskParams,
    TradeExecutionContext,
    TrailingStopState,
)

__all__ = [
    "ExecutionEngine",
    "DrawdownState",
    "ExecutionResult",
    "PositionSizeResult",
    "RiskCheckResult",
    "RiskParams",
    "TradeExecutionContext",
    "TrailingStopState",
]
