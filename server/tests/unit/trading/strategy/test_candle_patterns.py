"""candle_patterns.py 단위 테스트 — 5패턴 × 충족/미충족 (12건)."""
from __future__ import annotations

import pytest

from app.trading.indicators.types import CandleInput
from app.trading.strategy.candle_patterns import detect_patterns


def make_candle(
    open_: float, high: float, low: float, close: float, i: int = 0
) -> CandleInput:
    return CandleInput(
        timestamp=float(i * 300),
        open=open_, high=high, low=low, close=close, volume=1000.0,
    )


# ── 해머 ──────────────────────────────────────────────────────────────────────

class TestHammer:
    def test_hammer_detected(self):
        """해머 조건 충족: 아래꼬리≥몸통×2, 위꼬리≤몸통×0.5, 몸통비율>10%"""
        # 몸통=1, 아래꼬리=5, 위꼬리=0.3 → hammer
        prev = make_candle(103.0, 104.0, 101.0, 102.0, 0)
        curr = make_candle(100.0, 101.3, 95.0, 101.0, 1)
        patterns = detect_patterns([prev, curr])
        names = [p["pattern"] for p in patterns]
        assert "hammer" in names

    def test_hammer_is_bullish(self):
        prev = make_candle(103.0, 104.0, 101.0, 102.0, 0)
        curr = make_candle(100.0, 101.3, 95.0, 101.0, 1)
        patterns = detect_patterns([prev, curr], bullish_only=True)
        assert any(p["pattern"] == "hammer" for p in patterns)

    def test_hammer_not_detected_small_lower_shadow(self):
        """아래꼬리가 몸통의 2배 미만이면 해머 아님."""
        # 몸통=1, 아래꼬리=1.5(몸통×1.5, 2배 미달), 위꼬리=0.3
        prev = make_candle(103.0, 104.0, 101.0, 102.0, 0)
        curr = make_candle(100.0, 100.3, 98.5, 101.0, 1)
        patterns = detect_patterns([prev, curr])
        names = [p["pattern"] for p in patterns]
        assert "hammer" not in names


# ── Bullish Engulfing ─────────────────────────────────────────────────────────

class TestBullishEngulfing:
    def test_bullish_engulfing_detected(self):
        """직전 음봉을 현재 양봉이 완전히 감싸는 패턴."""
        prev = make_candle(102.0, 103.0, 99.0, 100.0, 0)  # 음봉
        curr = make_candle(99.0, 104.0, 98.5, 103.0, 1)   # 양봉, 감싸기
        patterns = detect_patterns([prev, curr])
        names = [p["pattern"] for p in patterns]
        assert "bullish_engulfing" in names

    def test_bullish_engulfing_not_detected_when_prev_bullish(self):
        """직전봉이 양봉이면 Bullish Engulfing 불가."""
        prev = make_candle(99.0, 103.0, 98.5, 102.0, 0)   # 양봉
        curr = make_candle(99.0, 104.0, 98.5, 103.0, 1)   # 양봉
        patterns = detect_patterns([prev, curr])
        names = [p["pattern"] for p in patterns]
        assert "bullish_engulfing" not in names

    def test_bullish_engulfing_not_detected_when_not_engulfing(self):
        """현재봉이 직전봉을 완전히 감싸지 않으면 불가."""
        prev = make_candle(102.0, 103.0, 99.0, 100.0, 0)  # 음봉
        curr = make_candle(100.5, 103.0, 99.5, 102.5, 1)  # 양봉이지만 감싸지 않음
        patterns = detect_patterns([prev, curr])
        names = [p["pattern"] for p in patterns]
        assert "bullish_engulfing" not in names


# ── Shooting Star ─────────────────────────────────────────────────────────────

class TestShootingStar:
    def test_shooting_star_detected(self):
        """위꼬리≥몸통×2, 아래꼬리≤몸통×0.5."""
        # 몸통=1 (open=100 close=99), 위꼬리=2.5, 아래꼬리=0.2
        prev = make_candle(98.0, 99.0, 97.0, 98.5, 0)
        curr = make_candle(100.0, 102.5, 99.8, 99.0, 1)
        patterns = detect_patterns([prev, curr])
        names = [p["pattern"] for p in patterns]
        assert "shooting_star" in names

    def test_shooting_star_is_bearish(self):
        prev = make_candle(98.0, 99.0, 97.0, 98.5, 0)
        curr = make_candle(100.0, 102.5, 99.8, 99.0, 1)
        patterns = detect_patterns([prev, curr], bearish_only=True)
        assert any(p["pattern"] == "shooting_star" for p in patterns)

    def test_shooting_star_not_in_bullish_only(self):
        prev = make_candle(98.0, 99.0, 97.0, 98.5, 0)
        curr = make_candle(100.0, 102.5, 99.8, 99.0, 1)
        patterns = detect_patterns([prev, curr], bullish_only=True)
        assert all(p["pattern"] != "shooting_star" for p in patterns)


# ── Bearish Engulfing ─────────────────────────────────────────────────────────

class TestBearishEngulfing:
    def test_bearish_engulfing_detected(self):
        """직전 양봉을 현재 음봉이 완전히 감싸는 패턴."""
        prev = make_candle(99.0, 103.0, 98.5, 102.0, 0)   # 양봉
        curr = make_candle(103.0, 104.0, 98.0, 98.5, 1)   # 음봉, 감싸기
        patterns = detect_patterns([prev, curr])
        names = [p["pattern"] for p in patterns]
        assert "bearish_engulfing" in names

    def test_bearish_engulfing_is_bearish(self):
        prev = make_candle(99.0, 103.0, 98.5, 102.0, 0)
        curr = make_candle(103.0, 104.0, 98.0, 98.5, 1)
        patterns = detect_patterns([prev, curr], bearish_only=True)
        assert any(p["pattern"] == "bearish_engulfing" for p in patterns)


# ── 도지 ──────────────────────────────────────────────────────────────────────

class TestDoji:
    def test_doji_detected(self):
        """몸통 ≤ 전체범위 × 10%."""
        # total_range=4, body=0.3 → 0.3/4 = 7.5% < 10% → 도지
        prev = make_candle(100.0, 101.0, 99.0, 100.5, 0)
        curr = make_candle(100.0, 102.0, 98.0, 100.3, 1)
        patterns = detect_patterns([prev, curr])
        names = [p["pattern"] for p in patterns]
        assert "doji" in names

    def test_doji_not_detected_when_body_large(self):
        """몸통이 전체범위의 10% 초과이면 도지 아님."""
        # body=1.5, total_range=2 → 75% > 10%
        prev = make_candle(100.0, 101.0, 99.0, 100.0, 0)
        curr = make_candle(99.0, 101.0, 99.0, 100.5, 1)  # body=1.5, range=2
        patterns = detect_patterns([prev, curr])
        names = [p["pattern"] for p in patterns]
        assert "doji" not in names


# ── 엣지 케이스 ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_candles(self):
        patterns = detect_patterns([])
        assert patterns == []

    def test_single_candle(self):
        """캔들 1개는 2봉 패턴 탐지 불가."""
        curr = make_candle(100.0, 101.3, 95.0, 101.0, 0)
        patterns = detect_patterns([curr])
        assert patterns == []
