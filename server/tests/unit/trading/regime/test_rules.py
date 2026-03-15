"""trading/regime/rules.py 단위 테스트."""
from __future__ import annotations

import pytest

from app.trading.indicators.types import (
    ADXResult,
    BollingerResult,
    EMAResult,
    IndicatorResult,
    MACDResult,
    StochasticResult,
    VWAPResult,
)
from app.trading.regime.rules import (
    check_adx_strength,
    check_bollinger_regime,
    check_ema_alignment,
    check_macd_momentum,
    check_rsi_regime,
)


def _make_indicators(**kwargs) -> IndicatorResult:
    """테스트용 IndicatorResult 생성. 미지정 필드는 None으로 채움."""
    defaults = IndicatorResult(
        ema=EMAResult(ema_20=None, ema_50=None, ema_200=None),
        vwap=VWAPResult(vwap=None, upper_band=None, lower_band=None),
        macd=MACDResult(macd_line=None, signal_line=None, histogram=None),
        rsi=None,
        stochastic=StochasticResult(k=None, d=None),
        williams_r=None,
        cci=None,
        bollinger=BollingerResult(upper=None, middle=None, lower=None, bandwidth=None, percent_b=None),
        atr=None,
        adx=ADXResult(adx=None, di_plus=None, di_minus=None),
        obv=None,
    )
    defaults.update(kwargs)
    return defaults


# ── check_adx_strength ────────────────────────────────────────────────────────

class TestCheckAdxStrength:
    def test_adx_none_returns_none(self):
        ind = _make_indicators(adx=ADXResult(adx=None, di_plus=None, di_minus=None))
        assert check_adx_strength(ind) is None

    def test_adx_above_threshold_returns_trend(self):
        ind = _make_indicators(adx=ADXResult(adx=35.0, di_plus=20.0, di_minus=10.0))
        result = check_adx_strength(ind)
        assert result is not None
        assert result["regime"] == "trend"
        assert result["strength"] == pytest.approx((35.0 - 25.0) / 25.0)

    def test_adx_strength_capped_at_1(self):
        ind = _make_indicators(adx=ADXResult(adx=60.0, di_plus=30.0, di_minus=10.0))
        result = check_adx_strength(ind)
        assert result is not None
        assert result["strength"] == 1.0

    def test_adx_below_range_threshold_returns_range(self):
        ind = _make_indicators(adx=ADXResult(adx=10.0, di_plus=None, di_minus=None))
        result = check_adx_strength(ind)
        assert result is not None
        assert result["regime"] == "range"
        assert result["strength"] == pytest.approx((20.0 - 10.0) / 20.0)

    def test_adx_transition_zone(self):
        ind = _make_indicators(adx=ADXResult(adx=22.0, di_plus=None, di_minus=None))
        result = check_adx_strength(ind)
        assert result is not None
        assert result["regime"] == "transition"
        assert result["strength"] == 0.5

    def test_adx_at_trend_boundary(self):
        ind = _make_indicators(adx=ADXResult(adx=25.0, di_plus=None, di_minus=None))
        result = check_adx_strength(ind)
        # 25.0 is NOT > 25.0, so it falls to transition check (25 is not < 20 either)
        assert result is not None
        assert result["regime"] == "transition"


# ── check_ema_alignment ───────────────────────────────────────────────────────

class TestCheckEmaAlignment:
    def test_both_ema_none_returns_none(self):
        ind = _make_indicators(ema=EMAResult(ema_20=None, ema_50=None, ema_200=None))
        assert check_ema_alignment(ind) is None

    def test_one_ema_none_returns_none(self):
        ind = _make_indicators(ema=EMAResult(ema_20=100.0, ema_50=None, ema_200=None))
        assert check_ema_alignment(ind) is None

    def test_bullish_alignment_returns_trend(self):
        ind = _make_indicators(ema=EMAResult(ema_20=110.0, ema_50=100.0, ema_200=90.0))
        result = check_ema_alignment(ind)
        assert result is not None
        assert result["regime"] == "trend"
        assert result["strength"] == 1.0

    def test_bearish_alignment_returns_trend(self):
        ind = _make_indicators(ema=EMAResult(ema_20=90.0, ema_50=100.0, ema_200=110.0))
        result = check_ema_alignment(ind)
        assert result is not None
        assert result["regime"] == "trend"
        assert result["strength"] == 1.0

    def test_ema_convergence_returns_range(self):
        # All EMAs very close together
        ind = _make_indicators(ema=EMAResult(ema_20=100.0, ema_50=100.1, ema_200=100.2))
        result = check_ema_alignment(ind)
        assert result is not None
        assert result["regime"] == "range"
        assert result["strength"] == 0.7

    def test_partial_alignment_returns_transition(self):
        ind = _make_indicators(ema=EMAResult(ema_20=110.0, ema_50=90.0, ema_200=100.0))
        result = check_ema_alignment(ind)
        assert result is not None
        assert result["regime"] == "transition"


# ── check_macd_momentum ───────────────────────────────────────────────────────

class TestCheckMacdMomentum:
    def test_histogram_none_returns_none(self):
        ind = _make_indicators(macd=MACDResult(macd_line=None, signal_line=None, histogram=None))
        assert check_macd_momentum(ind) is None

    def test_crossover_imminent_returns_transition(self):
        # |histogram| < |signal_line| * 0.1
        ind = _make_indicators(macd=MACDResult(macd_line=100.0, signal_line=100.0, histogram=5.0))
        result = check_macd_momentum(ind)
        assert result is not None
        assert result["regime"] == "transition"

    def test_large_positive_histogram_returns_trend(self):
        ind = _make_indicators(macd=MACDResult(macd_line=200.0, signal_line=100.0, histogram=100.0))
        result = check_macd_momentum(ind)
        assert result is not None
        assert result["regime"] == "trend"

    def test_large_negative_histogram_returns_trend(self):
        ind = _make_indicators(macd=MACDResult(macd_line=-200.0, signal_line=-100.0, histogram=-100.0))
        result = check_macd_momentum(ind)
        assert result is not None
        assert result["regime"] == "trend"


# ── check_rsi_regime ──────────────────────────────────────────────────────────

class TestCheckRsiRegime:
    def test_rsi_none_returns_none(self):
        ind = _make_indicators(rsi=None)
        assert check_rsi_regime(ind) is None

    def test_rsi_neutral_returns_range(self):
        ind = _make_indicators(rsi=50.0)
        result = check_rsi_regime(ind)
        assert result is not None
        assert result["regime"] == "range"
        assert result["strength"] == pytest.approx(1.0)

    def test_rsi_at_range_boundary(self):
        ind = _make_indicators(rsi=40.0)
        result = check_rsi_regime(ind)
        assert result is not None
        assert result["regime"] == "range"
        assert result["strength"] == pytest.approx(0.0)

    def test_rsi_overbought_returns_trend(self):
        ind = _make_indicators(rsi=75.0)
        result = check_rsi_regime(ind)
        assert result is not None
        assert result["regime"] == "trend"

    def test_rsi_oversold_returns_trend(self):
        ind = _make_indicators(rsi=25.0)
        result = check_rsi_regime(ind)
        assert result is not None
        assert result["regime"] == "trend"

    def test_rsi_transition_upper(self):
        ind = _make_indicators(rsi=65.0)
        result = check_rsi_regime(ind)
        assert result is not None
        assert result["regime"] == "transition"

    def test_rsi_transition_lower(self):
        ind = _make_indicators(rsi=35.0)
        result = check_rsi_regime(ind)
        assert result is not None
        assert result["regime"] == "transition"


# ── check_bollinger_regime ────────────────────────────────────────────────────

class TestCheckBollingerRegime:
    def test_bandwidth_none_returns_none(self):
        ind = _make_indicators(bollinger=BollingerResult(
            upper=None, middle=None, lower=None, bandwidth=None, percent_b=None
        ))
        assert check_bollinger_regime(ind) is None

    def test_narrow_bandwidth_returns_range(self):
        ind = _make_indicators(bollinger=BollingerResult(
            upper=None, middle=None, lower=None, bandwidth=0.02, percent_b=0.5
        ))
        result = check_bollinger_regime(ind)
        assert result is not None
        assert result["regime"] == "range"

    def test_wide_bandwidth_returns_trend(self):
        ind = _make_indicators(bollinger=BollingerResult(
            upper=None, middle=None, lower=None, bandwidth=0.20, percent_b=0.5
        ))
        result = check_bollinger_regime(ind)
        assert result is not None
        assert result["regime"] == "trend"

    def test_percent_b_extreme_upper_returns_transition(self):
        ind = _make_indicators(bollinger=BollingerResult(
            upper=None, middle=None, lower=None, bandwidth=0.10, percent_b=0.98
        ))
        result = check_bollinger_regime(ind)
        assert result is not None
        assert result["regime"] == "transition"

    def test_percent_b_extreme_lower_returns_transition(self):
        ind = _make_indicators(bollinger=BollingerResult(
            upper=None, middle=None, lower=None, bandwidth=0.10, percent_b=0.02
        ))
        result = check_bollinger_regime(ind)
        assert result is not None
        assert result["regime"] == "transition"
