"""전략 D: RSI+볼밴+반전캔들 3중 조건 전략.

PRD §7.4.1 전략 D 기준.
횡보 장세에서 RSI 과매도 + 볼린저 하단 + 반전 캔들 3조건 동시 충족 시 매수.
"""
from __future__ import annotations

import logging

from app.trading.indicators.types import CandleInput, IndicatorResult
from app.trading.regime.types import RegimeType

from .base import TradingStrategy
from .candle_patterns import detect_patterns
from .types import ConditionResult, SignalStrength, StrategyName, StrategySignal

logger = logging.getLogger(__name__)

# ── 전략 D 상수 ────────────────────────────────────────────────────────────────

RSI_BB_RSI_MAX = 30.0
RSI_BB_STOCH_K_MAX = 20.0
RSI_BB_PERCENT_B_MAX = 0.05


class RSIBBReversalStrategy(TradingStrategy):
    """전략 D: RSI+볼밴+반전캔들 3중 조건.

    RSI 과매도 + 볼린저 하단 + 반전 캔들 3조건이 동시에 충족될 때만 진입.
    """

    @property
    def name(self) -> StrategyName:
        return "rsi_bb_reversal"

    @property
    def compatible_regimes(self) -> list[RegimeType]:
        return ["range"]

    @property
    def stop_loss_atr_mult(self) -> float:
        return 1.0

    @property
    def take_profit_atr_mult(self) -> float:
        return 1.5

    @property
    def risk_reward_ratio(self) -> float:
        return 1.5  # PRD 1:1.5~2.0 범위에서 하한값 채택 (보수적)

    def evaluate(
        self,
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> StrategySignal | None:
        """진입 조건 평가 (3그룹 조건 ALL 충족 필수).

        [조건 1] RSI(14) < 30 AND Stochastic %K < 20
        [조건 2] 가격 ≤ BB Lower Band AND %B < 0.05
        [조건 3] 반전 캔들 (해머 / Bullish Engulfing / 도지 중 하나)
        """
        if len(candles) < 2:
            logger.debug("RSIBBReversal: 캔들 부족")
            return None

        curr = candles[-1]
        close = curr["close"]
        atr = indicators["atr"]

        if atr is None or atr == 0:
            logger.debug("RSIBBReversal: ATR 없음")
            return None

        rsi = indicators["rsi"]
        stochastic = indicators["stochastic"]
        bollinger = indicators["bollinger"]

        stoch_k = stochastic["k"]
        bb_lower = bollinger["lower"]
        percent_b = bollinger["percent_b"]

        conditions: list[ConditionResult] = []

        # [조건 1] RSI < 30 AND Stochastic %K < 20
        cond1a = rsi is not None and rsi < RSI_BB_RSI_MAX
        cond1b = stoch_k is not None and stoch_k < RSI_BB_STOCH_K_MAX
        cond1 = cond1a and cond1b
        rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
        stoch_k_str = f"{stoch_k:.1f}" if stoch_k is not None else "N/A"
        conditions.append(ConditionResult(
            name="rsi_stoch_oversold",
            passed=cond1,
            detail=(
                f"RSI={rsi_str} < {RSI_BB_RSI_MAX} "
                f"AND %K={stoch_k_str} < {RSI_BB_STOCH_K_MAX}"
            ),
        ))

        # [조건 2] 가격 ≤ BB Lower AND %B < 0.05
        cond2a = bb_lower is not None and close <= bb_lower
        cond2b = percent_b is not None and percent_b < RSI_BB_PERCENT_B_MAX
        cond2 = cond2a and cond2b
        conditions.append(ConditionResult(
            name="bb_lower_touch",
            passed=cond2,
            detail=(
                f"close={close:.4f} {'<=' if cond2a else '>'} BB_lower="
                f"{f'{bb_lower:.4f}' if bb_lower is not None else 'N/A'}, "
                f"%B={f'{percent_b:.4f}' if percent_b is not None else 'N/A'} "
                f"< {RSI_BB_PERCENT_B_MAX}"
            ),
        ))

        # [조건 3] 반전 캔들 (해머 / Bullish Engulfing / 도지)
        bullish_patterns = detect_patterns(candles, bullish_only=True)
        cond3 = len(bullish_patterns) > 0
        pattern_names = [p["pattern"] for p in bullish_patterns] if bullish_patterns else []
        conditions.append(ConditionResult(
            name="reversal_candle",
            passed=cond3,
            detail=(
                f"상승 반전 패턴 감지: {pattern_names}"
                if cond3
                else "상승 반전 패턴 없음 (해머/Bullish Engulfing/도지 필요)"
            ),
        ))

        all_passed = all(c["passed"] for c in conditions)
        if not all_passed:
            failed = [c["name"] for c in conditions if not c["passed"]]
            logger.debug("RSIBBReversal: 조건 미충족 %s", failed)
            return None

        exit_params = self._build_exit_params(close, atr, "buy")
        passed_count = sum(1 for c in conditions if c["passed"])
        confidence = passed_count / len(conditions)
        strength: SignalStrength = "strong" if confidence >= 0.9 else "moderate"

        return StrategySignal(
            strategy_name=self.name,
            action="buy",
            confidence=confidence,
            entry_price=close,
            exit_params=exit_params,
            strength=strength,
            conditions=conditions,
            detail=(
                f"RSI+볼밴+반전캔들 3중 조건: RSI={rsi:.1f}, %K={stoch_k:.1f}, "
                f"BB하단 터치(%B={percent_b:.4f}), {pattern_names}"
            ),
        )
