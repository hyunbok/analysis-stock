"""TrendMAStrategy 단위 테스트 — 6조건 개별 미충족 + 전체 충족 (8건)."""
from __future__ import annotations

import pytest

from app.trading.indicators.types import ADXResult, EMAResult
from app.trading.strategy.trend_ma import TrendMAStrategy

from .conftest import make_candles, make_indicators


STRATEGY = TrendMAStrategy()

# 기본 전략 조건 충족 지표 팩토리
def _passing_indicators(close: float = 100.5):
    return make_indicators(
        ema=EMAResult(ema_20=close * 1.001, ema_50=close * 0.99, ema_200=close * 0.95),
        adx=ADXResult(adx=30.0, di_plus=25.0, di_minus=10.0),
        rsi=52.0,
        atr=1.0,
    )


def _passing_candles(n: int = 25, close: float = 100.5) -> list:
    """EMA20 근접 + 양봉 + 거래량 급증 캔들."""
    candles = make_candles(n - 1, base_price=100.0)
    # 마지막 캔들: 양봉 + 거래량 급증
    from .conftest import make_candle
    candles.append(make_candle(
        n,
        open_=100.0,
        high=101.0,
        low=99.5,
        close=close,
        volume=2000.0,  # 평균 1000 × 1.2 = 1200 초과
    ))
    return candles


class TestTrendMAAllPass:
    def test_all_conditions_pass(self):
        """6개 조건 모두 충족 시 StrategySignal 반환."""
        close = 100.5
        indicators = _passing_indicators(close)
        # ema_20을 close와 근접하게 (0.3% 이내)
        ema_20 = close * 1.002  # 0.2% 이내
        indicators["ema"] = EMAResult(
            ema_20=ema_20,
            ema_50=ema_20 * 0.99,
            ema_200=ema_20 * 0.95,
        )
        candles = _passing_candles(25, close)
        signal = STRATEGY.evaluate(candles, indicators)
        assert signal is not None
        assert signal["action"] == "buy"
        assert signal["strategy_name"] == "trend_ma"
        assert signal["confidence"] == 1.0  # 전체 충족


class TestTrendMAConditionFailures:
    def test_fail_ema_not_aligned(self):
        """EMA 역배열 시 None."""
        close = 100.5
        indicators = _passing_indicators(close)
        indicators["ema"] = EMAResult(ema_20=99.0, ema_50=100.0, ema_200=101.0)  # 역배열
        candles = _passing_candles(25, close)
        signal = STRATEGY.evaluate(candles, indicators)
        assert signal is None

    def test_fail_adx_too_low(self):
        """ADX < 25 시 None."""
        close = 100.5
        indicators = _passing_indicators(close)
        indicators["adx"] = ADXResult(adx=20.0, di_plus=25.0, di_minus=10.0)
        ema_20 = close * 1.002
        indicators["ema"] = EMAResult(ema_20=ema_20, ema_50=ema_20 * 0.99, ema_200=ema_20 * 0.95)
        candles = _passing_candles(25, close)
        signal = STRATEGY.evaluate(candles, indicators)
        assert signal is None

    def test_fail_ema20_not_close(self):
        """EMA20에서 가격이 1% 이상 떨어져있을 때 None."""
        close = 100.5
        indicators = _passing_indicators(close)
        ema_20 = close * 1.02  # 2% 이상 괴리
        indicators["ema"] = EMAResult(
            ema_20=ema_20, ema_50=ema_20 * 0.99, ema_200=ema_20 * 0.95
        )
        candles = _passing_candles(25, close)
        signal = STRATEGY.evaluate(candles, indicators)
        assert signal is None

    def test_fail_bearish_candle(self):
        """음봉 (close < open) 시 None."""
        close = 99.5  # open=100보다 낮음 → 음봉
        indicators = _passing_indicators(close)
        ema_20 = close * 1.002
        indicators["ema"] = EMAResult(ema_20=ema_20, ema_50=ema_20 * 0.99, ema_200=ema_20 * 0.95)
        candles = make_candles(24)
        from .conftest import make_candle
        candles.append(make_candle(
            24, open_=100.0, high=100.5, low=99.0, close=close, volume=2000.0
        ))
        signal = STRATEGY.evaluate(candles, indicators)
        assert signal is None

    def test_fail_volume_insufficient(self):
        """거래량 부족 시 None."""
        close = 100.5
        indicators = _passing_indicators(close)
        ema_20 = close * 1.002
        indicators["ema"] = EMAResult(ema_20=ema_20, ema_50=ema_20 * 0.99, ema_200=ema_20 * 0.95)
        # 모든 캔들 volume=1000, 마지막도 1000 → 평균×1.2 = 1200 미달
        candles = make_candles(24)
        from .conftest import make_candle
        candles.append(make_candle(
            24, open_=100.0, high=101.0, low=99.5, close=close, volume=1000.0
        ))
        signal = STRATEGY.evaluate(candles, indicators)
        assert signal is None

    def test_fail_rsi_too_low(self):
        """RSI < 40 시 None."""
        close = 100.5
        indicators = _passing_indicators(close)
        indicators["rsi"] = 35.0
        ema_20 = close * 1.002
        indicators["ema"] = EMAResult(ema_20=ema_20, ema_50=ema_20 * 0.99, ema_200=ema_20 * 0.95)
        candles = _passing_candles(25, close)
        signal = STRATEGY.evaluate(candles, indicators)
        assert signal is None

    def test_fail_rsi_too_high(self):
        """RSI > 65 시 None."""
        close = 100.5
        indicators = _passing_indicators(close)
        indicators["rsi"] = 70.0
        ema_20 = close * 1.002
        indicators["ema"] = EMAResult(ema_20=ema_20, ema_50=ema_20 * 0.99, ema_200=ema_20 * 0.95)
        candles = _passing_candles(25, close)
        signal = STRATEGY.evaluate(candles, indicators)
        assert signal is None

    def test_fail_no_atr(self):
        """ATR None 시 None."""
        close = 100.5
        indicators = _passing_indicators(close)
        indicators["atr"] = None
        candles = _passing_candles(25, close)
        signal = STRATEGY.evaluate(candles, indicators)
        assert signal is None
