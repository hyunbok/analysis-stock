"""전략 A: TrendMA 눌림목 전략.

PRD §7.4.1 전략 A 기준.
트렌드 장세에서 EMA20 눌림목 반등을 이용한 매수 전략.
"""
from __future__ import annotations

import logging

from app.trading.indicators.types import CandleInput, IndicatorResult
from app.trading.regime.types import RegimeType

from .base import TradingStrategy
from .types import ConditionResult, SignalStrength, StrategyName, StrategySignal

logger = logging.getLogger(__name__)

# ── 전략 A 상수 ────────────────────────────────────────────────────────────────

EMA_PROXIMITY_RATIO = 0.005     # |price - EMA20| / EMA20 < 0.5%
VOLUME_MA_PERIOD = 20           # 거래량 이동평균 기간
VOLUME_MULTIPLIER = 1.2         # 거래량 ≥ 평균 × 1.2
TREND_MA_RSI_LOW = 40.0
TREND_MA_RSI_HIGH = 65.0
TREND_MA_ADX_MIN = 25.0


class TrendMAStrategy(TradingStrategy):
    """전략 A: TrendMA 눌림목.

    EMA20/50/200 정배열 + ADX 강세 구간에서 EMA20 눌림목 반등 진입.
    """

    @property
    def name(self) -> StrategyName:
        return "trend_ma"

    @property
    def compatible_regimes(self) -> list[RegimeType]:
        return ["trend"]

    @property
    def stop_loss_atr_mult(self) -> float:
        return 1.5

    @property
    def take_profit_atr_mult(self) -> float:
        return 3.0

    @property
    def risk_reward_ratio(self) -> float:
        return 2.0

    def evaluate(
        self,
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> StrategySignal | None:
        """진입 조건 평가 (6개 조건 ALL 충족 필수).

        조건:
        1. EMA20 > EMA50 > EMA200 (정배열)
        2. ADX > 25, +DI > -DI
        3. |가격 - EMA20| / EMA20 < 0.5% (EMA20 근접)
        4. 현재봉 양봉 (close > open) — EMA20 반등
        5. 거래량 ≥ 최근 20봉 평균 × 1.2
        6. RSI 40~65
        """
        if len(candles) < VOLUME_MA_PERIOD:
            logger.debug("TrendMA: 캔들 부족 (%d < %d)", len(candles), VOLUME_MA_PERIOD)
            return None

        curr = candles[-1]
        close = curr["close"]
        atr = indicators["atr"]

        if atr is None or atr == 0:
            logger.debug("TrendMA: ATR 없음")
            return None

        ema = indicators["ema"]
        adx_result = indicators["adx"]
        rsi = indicators["rsi"]

        ema_20 = ema["ema_20"]
        ema_50 = ema["ema_50"]
        ema_200 = ema["ema_200"]
        adx = adx_result["adx"]
        di_plus = adx_result["di_plus"]
        di_minus = adx_result["di_minus"]

        conditions: list[ConditionResult] = []

        # 조건 1: EMA 정배열
        cond1 = (
            ema_20 is not None
            and ema_50 is not None
            and ema_200 is not None
            and ema_20 > ema_50 > ema_200
        )
        conditions.append(ConditionResult(
            name="ema_aligned",
            passed=cond1,
            detail=(
                f"EMA20={ema_20:.4f} > EMA50={ema_50:.4f} > EMA200={ema_200:.4f}"
                if ema_20 and ema_50 and ema_200
                else "EMA 데이터 없음"
            ),
        ))

        # 조건 2: ADX > 25, +DI > -DI
        cond2 = (
            adx is not None
            and di_plus is not None
            and di_minus is not None
            and adx > TREND_MA_ADX_MIN
            and di_plus > di_minus
        )
        conditions.append(ConditionResult(
            name="adx_trend",
            passed=cond2,
            detail=(
                f"ADX={adx:.1f} > {TREND_MA_ADX_MIN}, +DI={di_plus:.1f} > -DI={di_minus:.1f}"
                if adx and di_plus and di_minus
                else "ADX 데이터 없음"
            ),
        ))

        # 조건 3: EMA20 근접
        cond3 = (
            ema_20 is not None
            and abs(close - ema_20) / ema_20 < EMA_PROXIMITY_RATIO
        )
        conditions.append(ConditionResult(
            name="ema20_proximity",
            passed=cond3,
            detail=(
                f"|{close:.4f} - EMA20={ema_20:.4f}| / EMA20 = "
                f"{abs(close - ema_20) / ema_20:.4f} < {EMA_PROXIMITY_RATIO}"
                if ema_20
                else "EMA20 없음"
            ),
        ))

        # 조건 4: 현재봉 양봉
        cond4 = curr["close"] > curr["open"]
        conditions.append(ConditionResult(
            name="bullish_candle",
            passed=cond4,
            detail=f"close={close:.4f} {'>' if cond4 else '<='} open={curr['open']:.4f}",
        ))

        # 조건 5: 거래량 ≥ 최근 20봉 평균 × 1.2
        vol_list = [c["volume"] for c in candles[-VOLUME_MA_PERIOD:]]
        avg_volume = sum(vol_list) / len(vol_list) if vol_list else 0
        curr_volume = curr["volume"]
        cond5 = avg_volume > 0 and curr_volume >= avg_volume * VOLUME_MULTIPLIER
        conditions.append(ConditionResult(
            name="volume_surge",
            passed=cond5,
            detail=(
                f"volume={curr_volume:.2f} >= avg{VOLUME_MA_PERIOD}={avg_volume:.2f} "
                f"× {VOLUME_MULTIPLIER} = {avg_volume * VOLUME_MULTIPLIER:.2f}"
            ),
        ))

        # 조건 6: RSI 40~65
        cond6 = rsi is not None and TREND_MA_RSI_LOW <= rsi <= TREND_MA_RSI_HIGH
        conditions.append(ConditionResult(
            name="rsi_range",
            passed=cond6,
            detail=(
                f"RSI={rsi:.1f} in [{TREND_MA_RSI_LOW}, {TREND_MA_RSI_HIGH}]"
                if rsi is not None
                else "RSI 없음"
            ),
        ))

        all_passed = all(c["passed"] for c in conditions)
        if not all_passed:
            failed = [c["name"] for c in conditions if not c["passed"]]
            logger.debug("TrendMA: 조건 미충족 %s", failed)
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
                f"TrendMA 눌림목: EMA 정배열, ADX={adx:.1f}, "
                f"EMA20 근접, 양봉, 거래량 급증, RSI={rsi:.1f}"
            ),
        )
