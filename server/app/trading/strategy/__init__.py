"""매매 전략 엔진.

순수 계산 패키지 — FastAPI / DB / Redis 의존성 금지.
서비스 레이어에서는 SignalGenerator만 진입점으로 사용.
"""
from __future__ import annotations

from .signal_generator import SignalGenerator
from .types import (
    ConditionResult,
    ExitParams,
    MTFResult,
    StrategyName,
    StrategySelection,
    StrategySignal,
    TradingSignal,
)

__all__ = [
    # 진입점 (서비스 레이어에서 사용)
    "SignalGenerator",
    # 최종 출력 타입
    "TradingSignal",
    # 중간 타입 (서비스/로깅에서 참조)
    "StrategySignal",
    "StrategySelection",
    "ConditionResult",
    "ExitParams",
    "MTFResult",
    "StrategyName",
]
# Note: TradingStrategy ABC, 개별 전략 클래스, StrategySelector는 비공개.
# 서비스 → 전략 직접 접근 방지 (SignalGenerator를 통해서만 사용).
