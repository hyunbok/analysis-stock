"""SignalGenerator 단위 테스트 — MTF 7가지 조합 + 통합 흐름 (9건)."""
from __future__ import annotations

import pytest

from app.trading.indicators.types import ADXResult, EMAResult
from app.trading.strategy.signal_generator import (
    MTF_WEIGHT_BOTH_ALIGNED,
    MTF_WEIGHT_BOTH_NEUTRAL,
    MTF_WEIGHT_ONE_NEUTRAL,
    SignalGenerator,
    _verify_mtf,
)

from .conftest import make_candles, make_indicators, make_regime


GENERATOR = SignalGenerator()


def _trend_passing_setup(n: int = 25):
    """TrendMA 전략 조건 충족 셋업."""
    close = 100.5
    ema_20 = close * 1.002
    indicators = make_indicators(
        ema=EMAResult(ema_20=ema_20, ema_50=ema_20 * 0.99, ema_200=ema_20 * 0.95),
        adx=ADXResult(adx=30.0, di_plus=25.0, di_minus=10.0),
        rsi=52.0,
        atr=1.0,
    )
    candles = make_candles(n - 1)
    from .conftest import make_candle
    candles.append(make_candle(
        n, open_=100.0, high=101.0, low=99.5, close=close, volume=2000.0
    ))
    regime = make_regime("trend", confidence=0.8)
    return candles, indicators, regime


def _bullish_indicators():
    return make_indicators(
        ema=EMAResult(ema_20=105.0, ema_50=100.0, ema_200=95.0),
        rsi=60.0,
        atr=1.0,
    )


def _bearish_indicators():
    return make_indicators(
        ema=EMAResult(ema_20=95.0, ema_50=100.0, ema_200=105.0),
        rsi=40.0,
        atr=1.0,
    )


def _neutral_indicators():
    return make_indicators(
        ema=EMAResult(ema_20=100.0, ema_50=100.0, ema_200=100.0),
        rsi=50.0,
        atr=1.0,
    )


# ── MTF 7가지 조합 테스트 ────────────────────────────────────────────────────

class TestMTFVerify:
    def test_both_bullish_weight_1(self):
        """1h bullish + 4h bullish → weight=1.0, allowed=True."""
        result = _verify_mtf("buy", _bullish_indicators(), _bullish_indicators())
        assert result["allowed"] is True
        assert result["weight"] == MTF_WEIGHT_BOTH_ALIGNED

    def test_bullish_and_neutral_weight_075(self):
        """1h bullish + 4h neutral → weight=0.75, allowed=True."""
        result = _verify_mtf("buy", _bullish_indicators(), _neutral_indicators())
        assert result["allowed"] is True
        assert result["weight"] == MTF_WEIGHT_ONE_NEUTRAL

    def test_neutral_and_bullish_weight_075(self):
        """1h neutral + 4h bullish → weight=0.75, allowed=True."""
        result = _verify_mtf("buy", _neutral_indicators(), _bullish_indicators())
        assert result["allowed"] is True
        assert result["weight"] == MTF_WEIGHT_ONE_NEUTRAL

    def test_both_neutral_weight_05(self):
        """1h neutral + 4h neutral → weight=0.5, allowed=True."""
        result = _verify_mtf("buy", _neutral_indicators(), _neutral_indicators())
        assert result["allowed"] is True
        assert result["weight"] == MTF_WEIGHT_BOTH_NEUTRAL

    def test_bearish_bearish_blocks_buy(self):
        """1h bearish + 4h bearish → 매수 차단."""
        result = _verify_mtf("buy", _bearish_indicators(), _bearish_indicators())
        assert result["allowed"] is False
        assert result["weight"] == 0.0

    def test_bullish_bearish_blocks_buy(self):
        """1h bullish + 4h bearish → 매수 차단."""
        result = _verify_mtf("buy", _bullish_indicators(), _bearish_indicators())
        assert result["allowed"] is False

    def test_bearish_bullish_blocks_buy(self):
        """1h bearish + 4h bullish → 매수 차단."""
        result = _verify_mtf("buy", _bearish_indicators(), _bullish_indicators())
        assert result["allowed"] is False

    def test_no_mtf_data_returns_neutral_weight(self):
        """MTF 데이터 없으면 weight=0.5 (중립)."""
        result = _verify_mtf("buy", None, None)
        assert result["allowed"] is True
        assert result["weight"] == MTF_WEIGHT_BOTH_NEUTRAL


# ── SignalGenerator 통합 흐름 테스트 ─────────────────────────────────────────

class TestSignalGeneratorFlow:
    def test_hold_when_regime_confidence_low(self):
        """regime.confidence < 0.5 → None."""
        candles, indicators, _ = _trend_passing_setup()
        regime = make_regime("trend", confidence=0.3)
        result = GENERATOR.generate(candles, indicators, regime)
        assert result is None

    def test_mtf_blocks_signal(self):
        """MTF bearish bearish → 신호 None."""
        candles, indicators, regime = _trend_passing_setup()
        result = GENERATOR.generate(
            candles, indicators, regime,
            indicators_1h=_bearish_indicators(),
            indicators_4h=_bearish_indicators(),
        )
        assert result is None

    def test_final_confidence_calculation(self):
        """최종 confidence = regime × strategy × mtf_weight."""
        candles, indicators, regime = _trend_passing_setup()
        result = GENERATOR.generate(
            candles, indicators, regime,
            indicators_1h=_bullish_indicators(),
            indicators_4h=_bullish_indicators(),
        )
        if result is not None:
            # strategy confidence=1.0 (all passed), mtf_weight=1.0 (both bullish)
            expected = regime["confidence"] * 1.0 * 1.0
            assert abs(result["confidence"] - expected) < 1e-9
            assert result["regime_type"] == "trend"
            assert "exit_params" in result
            assert "stop_loss" in result["exit_params"]
