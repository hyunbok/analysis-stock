"""장세 분류 규칙 함수.

각 함수는 IndicatorResult를 입력받아 RuleSignal | None을 반환한다.
지표 값이 None이면 해당 규칙은 건너뛴다 (None 반환).

순수 함수 모듈 — FastAPI / DB / Redis 의존성 금지.
"""
from __future__ import annotations

import logging

from app.trading.indicators.types import IndicatorResult

from .types import RuleSignal

logger = logging.getLogger(__name__)

# ── 임계값 상수 ────────────────────────────────────────────────────────────────

# ADX 임계값
ADX_TREND_THRESHOLD = 25.0
ADX_RANGE_THRESHOLD = 20.0

# Bollinger Bandwidth 임계값
BB_NARROW_THRESHOLD = 0.05      # 횡보 판별
BB_WIDE_THRESHOLD = 0.15        # 추세 판별

# RSI 구간
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
RSI_RANGE_UPPER = 60.0
RSI_RANGE_LOWER = 40.0

# EMA 수렴 판별 (가격 대비 비율)
EMA_CONVERGENCE_RATIO = 0.005   # 0.5%

# MACD 크로스오버 임박 비율
MACD_CROSSOVER_RATIO = 0.1


# ── 규칙 함수 ──────────────────────────────────────────────────────────────────

def check_adx_strength(indicators: IndicatorResult) -> RuleSignal | None:
    """ADX 기반 추세 강도 판별.

    - ADX > 25: Trend (strength = min((adx - 25) / 25, 1.0))
    - ADX < 20: Range (strength = min((20 - adx) / 20, 1.0))
    - ADX 20~25: Transition (strength = 0.5)
    """
    adx_result = indicators["adx"]
    adx = adx_result["adx"]
    if adx is None:
        return None

    if adx > ADX_TREND_THRESHOLD:
        strength = min((adx - ADX_TREND_THRESHOLD) / ADX_TREND_THRESHOLD, 1.0)
        return RuleSignal(
            name="adx_strength",
            regime="trend",
            strength=strength,
            detail=f"ADX={adx:.1f} > {ADX_TREND_THRESHOLD} (추세 강도 강함)",
        )
    elif adx < ADX_RANGE_THRESHOLD:
        strength = min((ADX_RANGE_THRESHOLD - adx) / ADX_RANGE_THRESHOLD, 1.0)
        return RuleSignal(
            name="adx_strength",
            regime="range",
            strength=strength,
            detail=f"ADX={adx:.1f} < {ADX_RANGE_THRESHOLD} (추세 강도 약함, 횡보)",
        )
    else:
        # ADX 20~25: Transition
        return RuleSignal(
            name="adx_strength",
            regime="transition",
            strength=0.5,
            detail=f"ADX={adx:.1f} 전환 구간 ({ADX_RANGE_THRESHOLD}~{ADX_TREND_THRESHOLD})",
        )


def check_ema_alignment(indicators: IndicatorResult) -> RuleSignal | None:
    """EMA 정배열/역배열 판별.

    - 정배열 (ema_20 > ema_50 > ema_200): Trend (상승), strength 1.0
    - 역배열 (ema_20 < ema_50 < ema_200): Trend (하락), strength 1.0
    - 수렴 (모든 EMA 간 차이 < 0.5%): Range, strength 0.7
    - 부분 정렬: Transition, strength 0.5
    """
    ema_result = indicators["ema"]
    ema_20 = ema_result["ema_20"]
    ema_50 = ema_result["ema_50"]
    ema_200 = ema_result["ema_200"]

    if ema_20 is None or ema_50 is None:
        return None

    # 수렴 판별 (사용 가능한 EMA들 기준)
    if ema_200 is not None:
        # 모든 3개 EMA 사용 가능
        max_ema = max(ema_20, ema_50, ema_200)
        min_ema = min(ema_20, ema_50, ema_200)
        if max_ema > 0 and (max_ema - min_ema) / max_ema < EMA_CONVERGENCE_RATIO:
            return RuleSignal(
                name="ema_alignment",
                regime="range",
                strength=0.7,
                detail=f"EMA 수렴 (20={ema_20:.2f}, 50={ema_50:.2f}, 200={ema_200:.2f})",
            )

        # 정배열: ema_20 > ema_50 > ema_200
        if ema_20 > ema_50 > ema_200:
            return RuleSignal(
                name="ema_alignment",
                regime="trend",
                strength=1.0,
                detail=f"EMA 정배열 상승 (20={ema_20:.2f} > 50={ema_50:.2f} > 200={ema_200:.2f})",
            )

        # 역배열: ema_20 < ema_50 < ema_200
        if ema_20 < ema_50 < ema_200:
            return RuleSignal(
                name="ema_alignment",
                regime="trend",
                strength=1.0,
                detail=f"EMA 역배열 하락 (20={ema_20:.2f} < 50={ema_50:.2f} < 200={ema_200:.2f})",
            )

        # 부분 정렬
        return RuleSignal(
            name="ema_alignment",
            regime="transition",
            strength=0.5,
            detail=f"EMA 부분 정렬 (20={ema_20:.2f}, 50={ema_50:.2f}, 200={ema_200:.2f})",
        )
    else:
        # ema_200 없음: ema_20, ema_50만으로 판별
        max_ema = max(ema_20, ema_50)
        min_ema = min(ema_20, ema_50)
        if max_ema > 0 and (max_ema - min_ema) / max_ema < EMA_CONVERGENCE_RATIO:
            return RuleSignal(
                name="ema_alignment",
                regime="range",
                strength=0.7,
                detail=f"EMA 수렴 (20={ema_20:.2f}, 50={ema_50:.2f})",
            )
        if ema_20 > ema_50:
            return RuleSignal(
                name="ema_alignment",
                regime="trend",
                strength=0.7,
                detail=f"EMA 상승 정렬 (20={ema_20:.2f} > 50={ema_50:.2f})",
            )
        return RuleSignal(
            name="ema_alignment",
            regime="trend",
            strength=0.7,
            detail=f"EMA 하락 정렬 (20={ema_20:.2f} < 50={ema_50:.2f})",
        )


def check_macd_momentum(indicators: IndicatorResult) -> RuleSignal | None:
    """MACD 히스토그램 방향성 판별.

    - 크로스오버 임박 (|histogram| < |signal_line| * 0.1): Transition
    - 히스토그램 ≈ 0 (|histogram| < threshold): Range
    - 히스토그램 양수 확대 or 음수 확대: Trend
    Note: 단일 시점에서 히스토그램 절대값과 부호로 판별
    """
    macd_result = indicators["macd"]
    histogram = macd_result["histogram"]
    signal_line = macd_result["signal_line"]
    macd_line = macd_result["macd_line"]

    if histogram is None:
        return None

    abs_hist = abs(histogram)

    # 크로스오버 임박: |histogram| < |signal_line| * MACD_CROSSOVER_RATIO
    if signal_line is not None and abs(signal_line) > 0:
        if abs_hist < abs(signal_line) * MACD_CROSSOVER_RATIO:
            return RuleSignal(
                name="macd_momentum",
                regime="transition",
                strength=0.8,
                detail=f"MACD 크로스오버 임박 (hist={histogram:.4f}, signal={signal_line:.4f})",
            )

    # 히스토그램 거의 0: Range
    # threshold = |macd_line| * 0.05 또는 고정값 사용
    if macd_line is not None and abs(macd_line) > 0:
        threshold = abs(macd_line) * 0.05
    else:
        threshold = 1e-6

    if abs_hist < threshold:
        return RuleSignal(
            name="macd_momentum",
            regime="range",
            strength=0.6,
            detail=f"MACD 히스토그램 ≈ 0 (hist={histogram:.4f}, 횡보 구간)",
        )

    # 히스토그램 유의미: Trend
    direction = "양수" if histogram > 0 else "음수"
    return RuleSignal(
        name="macd_momentum",
        regime="trend",
        strength=min(abs_hist / max(abs(macd_line) if macd_line else 1.0, 1e-6), 1.0),
        detail=f"MACD 히스토그램 {direction} (hist={histogram:.4f})",
    )


def check_rsi_regime(indicators: IndicatorResult) -> RuleSignal | None:
    """RSI 기반 장세 판별.

    - RSI 40~60: Range (strength = 1.0 - abs(rsi - 50) / 10)
    - RSI > 70 or RSI < 30: Trend (과매수/과매도 추세)
    - RSI 30~40 or 60~70: Transition
    """
    rsi = indicators["rsi"]
    if rsi is None:
        return None

    if RSI_RANGE_LOWER <= rsi <= RSI_RANGE_UPPER:
        strength = 1.0 - abs(rsi - 50.0) / 10.0
        return RuleSignal(
            name="rsi_regime",
            regime="range",
            strength=max(strength, 0.0),
            detail=f"RSI={rsi:.1f} 중립 구간 ({RSI_RANGE_LOWER}~{RSI_RANGE_UPPER})",
        )
    elif rsi > RSI_OVERBOUGHT or rsi < RSI_OVERSOLD:
        strength = min(abs(rsi - 50.0) / 50.0, 1.0)
        direction = "과매수" if rsi > RSI_OVERBOUGHT else "과매도"
        return RuleSignal(
            name="rsi_regime",
            regime="trend",
            strength=strength,
            detail=f"RSI={rsi:.1f} {direction} 추세",
        )
    else:
        # RSI 30~40 or 60~70: Transition
        return RuleSignal(
            name="rsi_regime",
            regime="transition",
            strength=0.5,
            detail=f"RSI={rsi:.1f} 전환 구간",
        )


def check_bollinger_regime(indicators: IndicatorResult) -> RuleSignal | None:
    """Bollinger Bandwidth 기반 장세 판별.

    - bandwidth < 임계값 (0.05): Range (좁은 밴드 → 횡보)
    - bandwidth > 0.15: Trend (넓은 밴드 → 추세)
    - %B < 0.05 or %B > 0.95: Transition (밴드 이탈 → 전환 가능)
    """
    bb_result = indicators["bollinger"]
    bandwidth = bb_result["bandwidth"]
    percent_b = bb_result["percent_b"]

    if bandwidth is None:
        return None

    # %B 극단 이탈 먼저 체크 (우선순위 높음)
    if percent_b is not None:
        if percent_b < 0.05 or percent_b > 0.95:
            strength = min(abs(percent_b - 0.5) * 2.0, 1.0)
            direction = "상단 이탈" if percent_b > 0.95 else "하단 이탈"
            return RuleSignal(
                name="bollinger_regime",
                regime="transition",
                strength=strength,
                detail=f"BB %B={percent_b:.3f} {direction} (전환 신호)",
            )

    if bandwidth < BB_NARROW_THRESHOLD:
        strength = min((BB_NARROW_THRESHOLD - bandwidth) / BB_NARROW_THRESHOLD, 1.0)
        return RuleSignal(
            name="bollinger_regime",
            regime="range",
            strength=strength,
            detail=f"BB bandwidth={bandwidth:.3f} < {BB_NARROW_THRESHOLD} (좁은 밴드, 횡보)",
        )
    elif bandwidth > BB_WIDE_THRESHOLD:
        strength = min((bandwidth - BB_WIDE_THRESHOLD) / BB_WIDE_THRESHOLD, 1.0)
        return RuleSignal(
            name="bollinger_regime",
            regime="trend",
            strength=strength,
            detail=f"BB bandwidth={bandwidth:.3f} > {BB_WIDE_THRESHOLD} (넓은 밴드, 추세)",
        )
    else:
        # 중간 구간: 약한 신호
        mid = (BB_NARROW_THRESHOLD + BB_WIDE_THRESHOLD) / 2
        if bandwidth < mid:
            return RuleSignal(
                name="bollinger_regime",
                regime="range",
                strength=0.4,
                detail=f"BB bandwidth={bandwidth:.3f} 중간 구간 (약한 횡보 신호)",
            )
        else:
            return RuleSignal(
                name="bollinger_regime",
                regime="trend",
                strength=0.4,
                detail=f"BB bandwidth={bandwidth:.3f} 중간 구간 (약한 추세 신호)",
            )
