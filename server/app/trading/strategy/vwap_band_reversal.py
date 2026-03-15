"""전략 C: VWAP 밴드 반전 전략.

PRD §7.4.1 전략 C 기준.
횡보 장세에서 VWAP 하단밴드 터치 시 반전을 이용한 매수 전략.
"""
from __future__ import annotations

import logging

from app.trading.indicators.types import CandleInput, IndicatorResult
from app.trading.regime.types import RegimeType

from .base import TradingStrategy
from .candle_patterns import detect_patterns
from .types import ConditionResult, SignalStrength, StrategyName, StrategySignal

logger = logging.getLogger(__name__)

# ── 전략 C 상수 ────────────────────────────────────────────────────────────────

VWAP_BAND_ADX_MAX = 20.0
VWAP_BAND_BB_NARROW = 0.05          # BB Bandwidth 수축 기준
VWAP_BAND_RSI_MAX = 40.0
VWAP_BAND_PERCENT_B_MAX = 0.1


class VWAPBandReversalStrategy(TradingStrategy):
    """전략 C: VWAP 밴드 반전.

    횡보 장세에서 VWAP 하단밴드 터치 + 반전 캔들 + 과매도 조건 동시 충족 시 진입.
    """

    @property
    def name(self) -> StrategyName:
        return "vwap_band_reversal"

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
        return 1.5

    def evaluate(
        self,
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> StrategySignal | None:
        """진입 조건 평가 (6개 조건 ALL 충족 필수).

        조건:
        1. ADX < 20 (횡보 확인)
        2. BB Bandwidth 수축 — bandwidth < 0.05
        3. 가격 ≤ VWAP 하단밴드 (lower_band)
        4. 반전 캔들 패턴
        5. RSI < 40
        6. %B < 0.1
        """
        if len(candles) < 2:
            logger.debug("VWAPBandReversal: 캔들 부족")
            return None

        curr = candles[-1]
        close = curr["close"]
        atr = indicators["atr"]

        if atr is None or atr == 0:
            logger.debug("VWAPBandReversal: ATR 없음")
            return None

        adx_result = indicators["adx"]
        bollinger = indicators["bollinger"]
        vwap_result = indicators["vwap"]
        rsi = indicators["rsi"]

        adx = adx_result["adx"]
        bandwidth = bollinger["bandwidth"]
        percent_b = bollinger["percent_b"]
        lower_band = vwap_result["lower_band"]

        conditions: list[ConditionResult] = []

        # 조건 1: ADX < 20 (횡보)
        cond1 = adx is not None and adx < VWAP_BAND_ADX_MAX
        conditions.append(ConditionResult(
            name="adx_range",
            passed=cond1,
            detail=(
                f"ADX={adx:.1f} < {VWAP_BAND_ADX_MAX} (횡보)"
                if adx is not None
                else "ADX 없음"
            ),
        ))

        # 조건 2: BB Bandwidth 수축
        cond2 = bandwidth is not None and bandwidth < VWAP_BAND_BB_NARROW
        conditions.append(ConditionResult(
            name="bb_narrow",
            passed=cond2,
            detail=(
                f"BB Bandwidth={bandwidth:.4f} < {VWAP_BAND_BB_NARROW}"
                if bandwidth is not None
                else "BB 데이터 없음"
            ),
        ))

        # 조건 3: 가격 ≤ VWAP 하단밴드
        cond3 = lower_band is not None and close <= lower_band
        conditions.append(ConditionResult(
            name="price_at_vwap_lower",
            passed=cond3,
            detail=(
                f"close={close:.4f} {'<=' if cond3 else '>'} VWAP_lower={lower_band:.4f}"
                if lower_band is not None
                else "VWAP 하단밴드 없음"
            ),
        ))

        # 조건 4: 반전 캔들 패턴
        reversal_patterns = detect_patterns(candles)
        cond4 = len(reversal_patterns) > 0
        pattern_names = [p["pattern"] for p in reversal_patterns] if reversal_patterns else []
        conditions.append(ConditionResult(
            name="reversal_candle",
            passed=cond4,
            detail=(
                f"반전 패턴 감지: {pattern_names}"
                if cond4
                else "반전 패턴 없음"
            ),
        ))

        # 조건 5: RSI < 40
        cond5 = rsi is not None and rsi < VWAP_BAND_RSI_MAX
        conditions.append(ConditionResult(
            name="rsi_oversold",
            passed=cond5,
            detail=(
                f"RSI={rsi:.1f} < {VWAP_BAND_RSI_MAX}"
                if rsi is not None
                else "RSI 없음"
            ),
        ))

        # 조건 6: %B < 0.1
        cond6 = percent_b is not None and percent_b < VWAP_BAND_PERCENT_B_MAX
        conditions.append(ConditionResult(
            name="percent_b_low",
            passed=cond6,
            detail=(
                f"%B={percent_b:.4f} < {VWAP_BAND_PERCENT_B_MAX}"
                if percent_b is not None
                else "%B 없음"
            ),
        ))

        all_passed = all(c["passed"] for c in conditions)
        if not all_passed:
            failed = [c["name"] for c in conditions if not c["passed"]]
            logger.debug("VWAPBandReversal: 조건 미충족 %s", failed)
            return None

        exit_params = self._build_exit_params(close, atr, "buy")
        passed_count = sum(1 for c in conditions if c["passed"])
        confidence = passed_count / len(conditions)
        strength: SignalStrength = "moderate" if confidence >= 0.9 else "weak"

        return StrategySignal(
            strategy_name=self.name,
            action="buy",
            confidence=confidence,
            entry_price=close,
            exit_params=exit_params,
            strength=strength,
            conditions=conditions,
            detail=(
                f"VWAP 밴드 반전: ADX={adx:.1f}(횡보), BB수축={bandwidth:.4f}, "
                f"VWAP 하단밴드 터치, {pattern_names}, RSI={rsi:.1f}, %B={percent_b:.4f}"
            ),
        )
