"""전략 E: RSI 다이버전스 + MACD 전략.

PRD §7.4.1 전략 E 기준.
전환 장세에서 RSI Bullish Divergence + MACD Golden Cross 동시 충족 시 매수.
"""
from __future__ import annotations

import logging

import pandas as pd

from app.trading.indicators.types import CandleInput, IndicatorResult
from app.trading.regime.types import RegimeType

from .base import TradingStrategy
from .types import ConditionResult, SignalStrength, StrategyName, StrategySignal

logger = logging.getLogger(__name__)

# ── 전략 E 상수 ────────────────────────────────────────────────────────────────

DIVERGENCE_LOOKBACK = 50        # RSI 다이버전스 탐색 캔들 수
DIVERGENCE_MIN_GAP = 5          # 두 저점 간 최소 간격
RSI_DIV_ADX_MAX = 25.0
RSI_PERIOD = 14                 # RSI 계산 기간


# ── RSI 시계열 계산 헬퍼 (ADR-17-4) ────────────────────────────────────────────

def _calculate_rsi_series(candles: list[CandleInput], period: int = RSI_PERIOD) -> list[float]:
    """RSI 시계열 계산 (Wilder's smoothing, indicators/oscillator.py 동일 알고리즘).

    Args:
        candles: OHLCV 캔들 (시간순).
        period: RSI 기간. 기본 14.

    Returns:
        캔들 수만큼의 RSI 값 리스트 (초반부는 NaN → 0.0 처리).
    """
    if len(candles) < period + 1:
        return [0.0] * len(candles)

    close = pd.Series([c["close"] for c in candles], dtype=float)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return [0.0 if pd.isna(v) else float(v) for v in rsi]


def _find_local_minima(values: list[float], window: int = 2) -> list[int]:
    """로컬 최솟값 인덱스 탐색 (양옆 window봉보다 낮은 점).

    Args:
        values: 값 리스트.
        window: 비교 범위.

    Returns:
        로컬 최솟값 인덱스 리스트.
    """
    minima = []
    for i in range(window, len(values) - window):
        is_min = all(values[i] <= values[i - j] for j in range(1, window + 1))
        is_min = is_min and all(values[i] <= values[i + j] for j in range(1, window + 1))
        if is_min:
            minima.append(i)
    return minima


def _detect_bullish_divergence(
    candles: list[CandleInput],
    lookback: int = DIVERGENCE_LOOKBACK,
    min_gap: int = DIVERGENCE_MIN_GAP,
) -> tuple[bool, str]:
    """RSI Bullish Divergence 감지.

    Args:
        candles: OHLCV 캔들 (최근 lookback개 사용).
        lookback: 탐색 캔들 수.
        min_gap: 두 저점 간 최소 간격.

    Returns:
        (divergence_found, detail_string)
    """
    target = candles[-lookback:] if len(candles) >= lookback else candles

    if len(target) < min_gap * 2 + 4:
        return False, f"캔들 부족 ({len(target)}개)"

    rsi_series = _calculate_rsi_series(target)
    price_lows = [c["low"] for c in target]

    # 로컬 최솟값 인덱스 탐색
    price_minima = _find_local_minima(price_lows)
    rsi_minima = _find_local_minima(rsi_series)

    # 공통 인덱스 (가격과 RSI 모두 최솟값인 지점)
    common_indices = sorted(set(price_minima) & set(rsi_minima))

    if len(common_indices) < 2:
        return False, f"공통 저점 부족 (가격 저점: {price_minima}, RSI 저점: {rsi_minima})"

    # 최근 2개 저점으로 Bullish Divergence 판별
    for j in range(len(common_indices) - 1, 0, -1):
        idx2 = common_indices[j]      # 더 최근 저점
        idx1 = common_indices[j - 1]  # 직전 저점

        if idx2 - idx1 < min_gap:
            continue

        price_low_1 = price_lows[idx1]
        price_low_2 = price_lows[idx2]
        rsi_low_1 = rsi_series[idx1]
        rsi_low_2 = rsi_series[idx2]

        # Bullish Divergence: 가격 저점 ↓ + RSI 저점 ↑
        if price_low_2 < price_low_1 and rsi_low_2 > rsi_low_1:
            return True, (
                f"Bullish Divergence: 가격 {price_low_1:.4f}→{price_low_2:.4f}(↓), "
                f"RSI {rsi_low_1:.1f}→{rsi_low_2:.1f}(↑), "
                f"간격={idx2 - idx1}봉"
            )

    return False, "Bullish Divergence 없음 (가격↓+RSI↑ 패턴 미발견)"


class RSIDivergenceStrategy(TradingStrategy):
    """전략 E: RSI 다이버전스 + MACD.

    RSI Bullish Divergence + MACD Golden Cross 동시 충족 + ADX < 25 + OBV 상승.
    """

    @property
    def name(self) -> StrategyName:
        return "rsi_divergence"

    @property
    def compatible_regimes(self) -> list[RegimeType]:
        return ["transition"]

    @property
    def stop_loss_atr_mult(self) -> float:
        return 1.5

    @property
    def take_profit_atr_mult(self) -> float:
        return 3.75

    @property
    def risk_reward_ratio(self) -> float:
        return 2.5

    def evaluate(
        self,
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> StrategySignal | None:
        """진입 조건 평가 (4개 조건 ALL 충족 필수).

        조건:
        1. RSI Bullish Divergence (최근 50캔들 탐색)
        2. MACD Golden Cross — MACD선 > Signal선 + 히스토그램 음→양 전환
        3. ADX < 25 또는 감소 중 (추세 약화 구간)
        4. OBV 상승 전환 (최근 close 방향 간이 판별)
        """
        if len(candles) < DIVERGENCE_MIN_GAP * 2 + 10:
            logger.debug("RSIDivergence: 캔들 부족 (%d)", len(candles))
            return None

        curr = candles[-1]
        close = curr["close"]
        atr = indicators["atr"]

        if atr is None or atr == 0:
            logger.debug("RSIDivergence: ATR 없음")
            return None

        macd_result = indicators["macd"]
        adx_result = indicators["adx"]
        obv = indicators["obv"]

        macd_line = macd_result["macd_line"]
        signal_line = macd_result["signal_line"]
        histogram = macd_result["histogram"]
        adx = adx_result["adx"]

        conditions: list[ConditionResult] = []

        # 조건 1: RSI Bullish Divergence
        div_found, div_detail = _detect_bullish_divergence(candles)
        conditions.append(ConditionResult(
            name="rsi_bullish_divergence",
            passed=div_found,
            detail=div_detail,
        ))

        # 조건 2: MACD Golden Cross (MACD > Signal + 히스토그램 양수)
        cond2 = (
            macd_line is not None
            and signal_line is not None
            and histogram is not None
            and macd_line > signal_line
            and histogram > 0
        )
        conditions.append(ConditionResult(
            name="macd_golden_cross",
            passed=cond2,
            detail=(
                f"MACD={macd_line:.4f} > Signal={signal_line:.4f}, "
                f"Histogram={histogram:.4f}({'양수' if histogram and histogram > 0 else '음수'})"
                if macd_line is not None and signal_line is not None and histogram is not None
                else "MACD 데이터 없음"
            ),
        ))

        # 조건 3: ADX < 25 (추세 약화)
        cond3 = adx is not None and adx < RSI_DIV_ADX_MAX
        conditions.append(ConditionResult(
            name="adx_weak",
            passed=cond3,
            detail=(
                f"ADX={adx:.1f} < {RSI_DIV_ADX_MAX} (추세 약화)"
                if adx is not None
                else "ADX 없음"
            ),
        ))

        # 조건 4: OBV 상승 전환 (간이 판별 — ADR-17-3)
        lookback = min(5, len(candles) - 1)
        recent = candles[-(lookback + 1):]
        up_count = sum(
            1 for i in range(1, len(recent)) if recent[i]["close"] > recent[i - 1]["close"]
        )
        obv_rising = up_count > lookback // 2
        if obv is not None:
            obv_rising = obv_rising and obv > 0
        cond4 = obv_rising
        conditions.append(ConditionResult(
            name="obv_rising",
            passed=cond4,
            detail=(
                f"OBV 상승 전환: 최근 {lookback}봉 상승={up_count}봉, "
                f"OBV={f'{obv:.2f}' if obv is not None else 'N/A'}"
            ),
        ))

        all_passed = all(c["passed"] for c in conditions)
        if not all_passed:
            failed = [c["name"] for c in conditions if not c["passed"]]
            logger.debug("RSIDivergence: 조건 미충족 %s", failed)
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
                f"RSI 다이버전스+MACD: {div_detail}, "
                f"MACD={macd_line:.4f}/Signal={signal_line:.4f}, ADX={adx:.1f}"
            ),
        )
