"""trading/regime/classifier.py 통합 테스트."""
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
from app.trading.regime.classifier import classify_regime


def _make_indicators(**kwargs) -> IndicatorResult:
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


def _strong_trend_indicators() -> IndicatorResult:
    """강한 상승 추세 시나리오 (설계서 §11.4 ST1): 모든 규칙이 trend 지지.
    - ADX=50 (strength=1.0), EMA 정배열 (strength=1.0), RSI=78 과매수 (strength=0.56)
    - MACD hist=200 >> threshold (strength=0.5), BB bandwidth=0.20 (strength=0.33)
    """
    return _make_indicators(
        adx=ADXResult(adx=50.0, di_plus=35.0, di_minus=10.0),
        ema=EMAResult(ema_20=120.0, ema_50=100.0, ema_200=80.0),
        rsi=78.0,
        macd=MACDResult(macd_line=200.0, signal_line=100.0, histogram=200.0),
        bollinger=BollingerResult(upper=None, middle=None, lower=None, bandwidth=0.20, percent_b=0.75),
    )


def _range_indicators() -> IndicatorResult:
    """횡보장 시나리오: ADX=15, EMA 수렴, RSI=50, MACD≈0, BB=0.03."""
    return _make_indicators(
        adx=ADXResult(adx=15.0, di_plus=15.0, di_minus=14.0),
        ema=EMAResult(ema_20=100.0, ema_50=100.1, ema_200=100.2),
        rsi=50.0,
        macd=MACDResult(macd_line=10.0, signal_line=10.0, histogram=0.5),
        bollinger=BollingerResult(upper=None, middle=None, lower=None, bandwidth=0.03, percent_b=0.5),
    )


def _transition_indicators() -> IndicatorResult:
    """전환 구간 시나리오: ADX=22, EMA 부분 정렬, RSI=35, MACD 크로스오버 임박."""
    return _make_indicators(
        adx=ADXResult(adx=22.0, di_plus=18.0, di_minus=16.0),
        ema=EMAResult(ema_20=110.0, ema_50=90.0, ema_200=100.0),
        rsi=35.0,
        macd=MACDResult(macd_line=100.0, signal_line=100.0, histogram=5.0),
        bollinger=BollingerResult(upper=None, middle=None, lower=None, bandwidth=0.10, percent_b=0.5),
    )


class TestClassifyRegime:
    def test_strong_trend_returns_trend(self):
        result = classify_regime(_strong_trend_indicators())
        assert result["regime"] == "trend"
        # softmax T=1.0 (§5.3)에서 모든 규칙이 trend일 때 최대 ~0.53 — trend가 range/transition 압도
        assert result["confidence"] > result["scores"]["range"] * 2
        assert result["confidence"] > result["scores"]["transition"] * 2

    def test_range_returns_range(self):
        result = classify_regime(_range_indicators())
        assert result["regime"] == "range"

    def test_transition_triggers_gpt_condition(self):
        result = classify_regime(_transition_indicators())
        # 전환 시나리오는 confidence < 0.7 이거나 regime == "transition" → GPT 트리거 조건 충족
        needs_gpt = result["confidence"] < 0.7 or result["regime"] == "transition"
        assert needs_gpt, "전환 시나리오는 GPT 검증 조건(confidence < 0.7 or transition)을 충족해야 함"
        # gpt_validated should be False (pure classify_regime doesn't call GPT)
        assert result["gpt_validated"] is False
        assert result["gpt_agreement"] is None

    def test_result_has_all_required_fields(self):
        result = classify_regime(_strong_trend_indicators())
        assert "regime" in result
        assert "confidence" in result
        assert "scores" in result
        assert "signals" in result
        assert "gpt_validated" in result
        assert "gpt_agreement" in result

    def test_scores_sum_to_one(self):
        result = classify_regime(_strong_trend_indicators())
        total = result["scores"]["trend"] + result["scores"]["range"] + result["scores"]["transition"]
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_confidence_matches_winning_score(self):
        result = classify_regime(_strong_trend_indicators())
        assert result["confidence"] == pytest.approx(result["scores"][result["regime"]])

    def test_signals_non_empty(self):
        result = classify_regime(_strong_trend_indicators())
        assert len(result["signals"]) >= 2

    def test_insufficient_indicators_raises_valueerror(self):
        # Only ADX set, everything else None -> fewer than 2 active rules
        ind = _make_indicators(
            adx=ADXResult(adx=None, di_plus=None, di_minus=None),
            ema=EMAResult(ema_20=None, ema_50=None, ema_200=None),
            rsi=None,
            macd=MACDResult(macd_line=None, signal_line=None, histogram=None),
            bollinger=BollingerResult(upper=None, middle=None, lower=None, bandwidth=None, percent_b=None),
        )
        with pytest.raises(ValueError, match="최소"):
            classify_regime(ind)

    def test_all_scores_between_0_and_1(self):
        result = classify_regime(_range_indicators())
        for v in result["scores"].values():
            assert 0.0 <= v <= 1.0

    def test_gpt_not_called_in_classify(self):
        result = classify_regime(_strong_trend_indicators())
        assert result["gpt_validated"] is False
        assert result["gpt_agreement"] is None
