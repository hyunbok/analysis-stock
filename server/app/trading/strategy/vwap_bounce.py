"""전략 B: VWAP 눌림목 전략.

PRD §7.4.1 전략 B 기준.
트렌드 장세에서 VWAP 눌림목 지지를 이용한 매수 전략.
"""
from __future__ import annotations

import logging

from app.trading.indicators.types import CandleInput, IndicatorResult
from app.trading.regime.types import RegimeType

from .base import TradingStrategy
from .candle_patterns import detect_patterns
from .types import ConditionResult, SignalStrength, StrategyName, StrategySignal

logger = logging.getLogger(__name__)

# ── 전략 B 상수 ────────────────────────────────────────────────────────────────

VWAP_PROXIMITY_RATIO = 0.003    # |price - VWAP| / VWAP < 0.3%
VWAP_BOUNCE_ADX_MIN = 20.0
VWAP_BOUNCE_RSI_LOW = 40.0
VWAP_BOUNCE_RSI_HIGH = 65.0
OBV_LOOKBACK = 5                # OBV 상승 판별 lookback


class VWAPBounceStrategy(TradingStrategy):
    """전략 B: VWAP 눌림목.

    가격이 VWAP 위에서 VWAP에 근접 후 반등할 때 진입.
    """

    @property
    def name(self) -> StrategyName:
        return "vwap_bounce"

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
        1. 가격 > VWAP
        2. ADX > 20
        3. |가격 - VWAP| / VWAP < 0.3% (VWAP 터치)
        4. 반전 캔들 (해머 or Bullish Engulfing)
        5. RSI 40~65
        6. OBV 상승 추세 (최근 5봉 close 방향으로 간이 판별)
        """
        if len(candles) < OBV_LOOKBACK + 1:
            logger.debug("VWAPBounce: 캔들 부족 (%d)", len(candles))
            return None

        curr = candles[-1]
        close = curr["close"]
        atr = indicators["atr"]

        if atr is None or atr == 0:
            logger.debug("VWAPBounce: ATR 없음")
            return None

        vwap_result = indicators["vwap"]
        adx_result = indicators["adx"]
        rsi = indicators["rsi"]
        obv = indicators["obv"]

        vwap = vwap_result["vwap"]
        adx = adx_result["adx"]

        conditions: list[ConditionResult] = []

        # 조건 1: 가격 > VWAP
        cond1 = vwap is not None and close > vwap
        conditions.append(ConditionResult(
            name="price_above_vwap",
            passed=cond1,
            detail=(
                f"close={close:.4f} {'>' if cond1 else '<='} VWAP={vwap:.4f}"
                if vwap
                else "VWAP 없음"
            ),
        ))

        # 조건 2: ADX > 20
        cond2 = adx is not None and adx > VWAP_BOUNCE_ADX_MIN
        conditions.append(ConditionResult(
            name="adx_min",
            passed=cond2,
            detail=(
                f"ADX={adx:.1f} > {VWAP_BOUNCE_ADX_MIN}"
                if adx is not None
                else "ADX 없음"
            ),
        ))

        # 조건 3: VWAP 근접
        cond3 = (
            vwap is not None
            and abs(close - vwap) / vwap < VWAP_PROXIMITY_RATIO
        )
        conditions.append(ConditionResult(
            name="vwap_proximity",
            passed=cond3,
            detail=(
                f"|{close:.4f} - VWAP={vwap:.4f}| / VWAP = "
                f"{abs(close - vwap) / vwap:.4f} < {VWAP_PROXIMITY_RATIO}"
                if vwap
                else "VWAP 없음"
            ),
        ))

        # 조건 4: 반전 캔들 (해머 or Bullish Engulfing)
        bullish_patterns = detect_patterns(candles, bullish_only=True)
        cond4 = len(bullish_patterns) > 0
        pattern_names = [p["pattern"] for p in bullish_patterns] if bullish_patterns else []
        conditions.append(ConditionResult(
            name="reversal_candle",
            passed=cond4,
            detail=(
                f"상승 반전 패턴 감지: {pattern_names}"
                if cond4
                else "상승 반전 패턴 없음"
            ),
        ))

        # 조건 5: RSI 40~65
        cond5 = rsi is not None and VWAP_BOUNCE_RSI_LOW <= rsi <= VWAP_BOUNCE_RSI_HIGH
        conditions.append(ConditionResult(
            name="rsi_range",
            passed=cond5,
            detail=(
                f"RSI={rsi:.1f} in [{VWAP_BOUNCE_RSI_LOW}, {VWAP_BOUNCE_RSI_HIGH}]"
                if rsi is not None
                else "RSI 없음"
            ),
        ))

        # 조건 6: OBV 상승 추세 (간이 판별 — ADR-17-3)
        # 최근 OBV_LOOKBACK 봉의 close 방향으로 추정
        recent = candles[-(OBV_LOOKBACK + 1):]
        up_count = sum(
            1 for i in range(1, len(recent)) if recent[i]["close"] > recent[i - 1]["close"]
        )
        obv_rising = up_count > OBV_LOOKBACK // 2
        # OBV 값이 있으면 추가 검증 (양수이면 순매수)
        if obv is not None:
            obv_rising = obv_rising and obv > 0
        cond6 = obv_rising
        conditions.append(ConditionResult(
            name="obv_rising",
            passed=cond6,
            detail=(
                f"OBV 상승 추세: 최근 {OBV_LOOKBACK}봉 상승={up_count}봉, "
                f"OBV={f'{obv:.2f}' if obv is not None else 'N/A'}"
            ),
        ))

        all_passed = all(c["passed"] for c in conditions)
        if not all_passed:
            failed = [c["name"] for c in conditions if not c["passed"]]
            logger.debug("VWAPBounce: 조건 미충족 %s", failed)
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
                f"VWAP 눌림목: VWAP 상단 유지, ADX={adx:.1f}, "
                f"VWAP 근접, {pattern_names}, RSI={rsi:.1f}"
            ),
        )
