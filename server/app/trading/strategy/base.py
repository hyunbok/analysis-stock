"""매매 전략 기본 클래스 (ABC).

순수 계산 패키지 — FastAPI / DB / Redis 의존성 없음.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.trading.indicators.types import CandleInput, IndicatorResult
from app.trading.regime.types import RegimeType

from .types import ExitParams, StrategyName, StrategySignal


class TradingStrategy(ABC):
    """매매 전략 기본 클래스.

    순수 계산 클래스 — DB / Redis / HTTP 의존성 없음.
    """

    @property
    @abstractmethod
    def name(self) -> StrategyName:
        """전략 식별자."""

    @property
    @abstractmethod
    def compatible_regimes(self) -> list[RegimeType]:
        """이 전략이 적용 가능한 장세 목록.

        StrategySelector가 1차 필터링에 사용.
        """

    @property
    @abstractmethod
    def stop_loss_atr_mult(self) -> float:
        """손절 ATR 배수 (PRD §7.5.3)."""

    @property
    @abstractmethod
    def take_profit_atr_mult(self) -> float:
        """익절 ATR 배수 (PRD §7.5.3)."""

    @property
    @abstractmethod
    def risk_reward_ratio(self) -> float:
        """목표 RR 비율."""

    @abstractmethod
    def evaluate(
        self,
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> StrategySignal | None:
        """진입 조건 평가.

        Args:
            candles: OHLCV 캔들 (시간순, 5분봉).
            indicators: 동일 캔들에 대한 기술적 지표 결과.

        Returns:
            조건 충족 시 StrategySignal, 미충족 시 None.

        Note:
            내부에서 전체 조건을 ConditionResult로 수집하되,
            모든 필수 조건 passed=True일 때만 StrategySignal 반환.
            미충족 시 None + logger.debug()로 어떤 조건이 실패했는지 기록.
        """

    def _build_exit_params(
        self,
        entry_price: float,
        atr: float,
        action: str,
    ) -> ExitParams:
        """ATR 기반 손절/익절 계산 헬퍼.

        공통 로직이므로 ABC에 제공.
        """
        if action == "buy":
            stop_loss = entry_price - atr * self.stop_loss_atr_mult
            take_profit = entry_price + atr * self.take_profit_atr_mult
        else:
            stop_loss = entry_price + atr * self.stop_loss_atr_mult
            take_profit = entry_price - atr * self.take_profit_atr_mult

        return ExitParams(
            stop_loss=stop_loss,
            take_profit=take_profit,
            stop_loss_atr_mult=self.stop_loss_atr_mult,
            take_profit_atr_mult=self.take_profit_atr_mult,
            risk_reward_ratio=self.risk_reward_ratio,
        )
