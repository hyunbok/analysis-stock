"""반전 캔들 패턴 감지 유틸리티.

순수 함수 모듈 — 외부 의존성 없음.
PRD §7.4.2 기준 5가지 패턴 구현.
"""
from __future__ import annotations

from app.trading.indicators.types import CandleInput

from .types import CandlePatternResult, CandlePatternType

# ── 캔들 패턴 상수 ─────────────────────────────────────────────────────────────

HAMMER_LOWER_SHADOW_MULT = 2.0        # 아래꼬리 ≥ 몸통 × 2
HAMMER_UPPER_SHADOW_MULT = 0.5        # 위꼬리 ≤ 몸통 × 0.5
DOJI_BODY_RATIO = 0.1                 # 몸통 ≤ 전체범위 × 10%
MIN_BODY_RANGE_RATIO = 0.1            # 해머 몸통/전체범위 > 10%


def _candle_parts(candle: CandleInput) -> tuple[float, float, float, float]:
    """캔들의 몸통, 위꼬리, 아래꼬리, 전체범위 반환."""
    o = candle["open"]
    h = candle["high"]
    l = candle["low"]
    c = candle["close"]

    body = abs(c - o)
    upper_shadow = h - max(c, o)
    lower_shadow = min(c, o) - l
    total_range = h - l

    return body, upper_shadow, lower_shadow, total_range


def _is_hammer(candle: CandleInput) -> CandlePatternResult | None:
    """해머 패턴 감지 (상승 반전).

    조건:
    - 아래꼬리 ≥ 몸통 × 2
    - 위꼬리 ≤ 몸통 × 0.5
    - 몸통/전체범위 > 10%
    """
    body, upper_shadow, lower_shadow, total_range = _candle_parts(candle)

    if total_range == 0 or body == 0:
        return None

    body_range_ratio = body / total_range
    if body_range_ratio <= MIN_BODY_RANGE_RATIO:
        return None

    if (lower_shadow >= body * HAMMER_LOWER_SHADOW_MULT
            and upper_shadow <= body * HAMMER_UPPER_SHADOW_MULT):
        return CandlePatternResult(
            pattern="hammer",
            is_bullish=True,
            detail=(
                f"Hammer: 아래꼬리={lower_shadow:.4f}(몸통×{lower_shadow/body:.1f}), "
                f"위꼬리={upper_shadow:.4f}, 몸통비율={body_range_ratio:.2%}"
            ),
        )
    return None


def _is_bullish_engulfing(
    prev: CandleInput, curr: CandleInput
) -> CandlePatternResult | None:
    """Bullish Engulfing 패턴 감지 (상승 반전).

    조건:
    - 직전 음봉 (prev_close < prev_open)
    - 현재 양봉 (curr_close > curr_open)
    - 현재 봉이 직전 봉을 완전히 감싸는 패턴
      (curr_open <= prev_close, curr_close >= prev_open)
    """
    prev_bullish = prev["close"] > prev["open"]
    curr_bullish = curr["close"] > curr["open"]

    if prev_bullish or not curr_bullish:
        return None

    if curr["open"] <= prev["close"] and curr["close"] >= prev["open"]:
        return CandlePatternResult(
            pattern="bullish_engulfing",
            is_bullish=True,
            detail=(
                f"Bullish Engulfing: prev={prev['open']:.4f}/{prev['close']:.4f}, "
                f"curr={curr['open']:.4f}/{curr['close']:.4f}"
            ),
        )
    return None


def _is_shooting_star(candle: CandleInput) -> CandlePatternResult | None:
    """Shooting Star 패턴 감지 (하락 반전).

    조건:
    - 위꼬리 ≥ 몸통 × 2
    - 아래꼬리 ≤ 몸통 × 0.5
    - 몸통/전체범위 > 10%
    """
    body, upper_shadow, lower_shadow, total_range = _candle_parts(candle)

    if total_range == 0 or body == 0:
        return None

    body_range_ratio = body / total_range
    if body_range_ratio <= MIN_BODY_RANGE_RATIO:
        return None

    if (upper_shadow >= body * HAMMER_LOWER_SHADOW_MULT
            and lower_shadow <= body * HAMMER_UPPER_SHADOW_MULT):
        return CandlePatternResult(
            pattern="shooting_star",
            is_bullish=False,
            detail=(
                f"Shooting Star: 위꼬리={upper_shadow:.4f}(몸통×{upper_shadow/body:.1f}), "
                f"아래꼬리={lower_shadow:.4f}, 몸통비율={body_range_ratio:.2%}"
            ),
        )
    return None


def _is_bearish_engulfing(
    prev: CandleInput, curr: CandleInput
) -> CandlePatternResult | None:
    """Bearish Engulfing 패턴 감지 (하락 반전).

    조건:
    - 직전 양봉 (prev_close > prev_open)
    - 현재 음봉 (curr_close < curr_open)
    - 현재 봉이 직전 봉을 완전히 감싸는 패턴
      (curr_open >= prev_close, curr_close <= prev_open)
    """
    prev_bullish = prev["close"] > prev["open"]
    curr_bullish = curr["close"] > curr["open"]

    if not prev_bullish or curr_bullish:
        return None

    if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
        return CandlePatternResult(
            pattern="bearish_engulfing",
            is_bullish=False,
            detail=(
                f"Bearish Engulfing: prev={prev['open']:.4f}/{prev['close']:.4f}, "
                f"curr={curr['open']:.4f}/{curr['close']:.4f}"
            ),
        )
    return None


def _is_doji(candle: CandleInput) -> CandlePatternResult | None:
    """도지 패턴 감지 (context-dependent).

    조건:
    - 몸통 ≤ 전체범위 × 10%
    """
    body, _, _, total_range = _candle_parts(candle)

    if total_range == 0:
        return None

    if body <= total_range * DOJI_BODY_RATIO:
        return CandlePatternResult(
            pattern="doji",
            is_bullish=True,  # 전략 컨텍스트에서 결정 (기본 상승 반전으로 취급)
            detail=(
                f"Doji: 몸통={body:.4f}, 전체범위={total_range:.4f}, "
                f"비율={body/total_range:.2%}"
            ),
        )
    return None


def detect_patterns(
    candles: list[CandleInput],
    *,
    bullish_only: bool = False,
    bearish_only: bool = False,
) -> list[CandlePatternResult]:
    """최근 2개 캔들에서 반전 패턴 감지.

    Args:
        candles: 최소 2개 캔들 (시간순).
        bullish_only: True면 상승 반전 패턴만 반환.
        bearish_only: True면 하락 반전 패턴만 반환.

    Returns:
        감지된 패턴 리스트 (없으면 빈 리스트).
    """
    if len(candles) < 2:
        return []

    prev = candles[-2]
    curr = candles[-1]

    patterns: list[CandlePatternResult] = []

    # 단봉 패턴 (현재 캔들만)
    if result := _is_hammer(curr):
        patterns.append(result)

    if result := _is_shooting_star(curr):
        patterns.append(result)

    if result := _is_doji(curr):
        patterns.append(result)

    # 2봉 패턴 (직전 + 현재)
    if result := _is_bullish_engulfing(prev, curr):
        patterns.append(result)

    if result := _is_bearish_engulfing(prev, curr):
        patterns.append(result)

    # 필터링
    if bullish_only:
        return [p for p in patterns if p["is_bullish"]]
    if bearish_only:
        return [p for p in patterns if not p["is_bullish"]]

    return patterns
