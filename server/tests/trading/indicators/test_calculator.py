"""calculator.py 통합 테스트 — calculate_all_indicators."""
from __future__ import annotations

import pytest

from app.trading.indicators import calculate_all_indicators
from app.trading.indicators.types import CandleInput


class TestCalculateAllIndicators:
    def test_normal_200_candles(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)

        # 모든 키 존재
        assert "ema" in result
        assert "vwap" in result
        assert "macd" in result
        assert "rsi" in result
        assert "stochastic" in result
        assert "williams_r" in result
        assert "cci" in result
        assert "bollinger" in result
        assert "atr" in result
        assert "adx" in result
        assert "obv" in result

    def test_ema_result_structure(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        ema = result["ema"]
        assert "ema_20" in ema
        assert "ema_50" in ema
        assert "ema_200" in ema

    def test_macd_result_structure(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        macd = result["macd"]
        assert "macd_line" in macd
        assert "signal_line" in macd
        assert "histogram" in macd

    def test_vwap_result_structure(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        vwap = result["vwap"]
        assert "vwap" in vwap
        assert "upper_band" in vwap
        assert "lower_band" in vwap

    def test_bollinger_result_structure(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        bb = result["bollinger"]
        assert "upper" in bb
        assert "middle" in bb
        assert "lower" in bb
        assert "bandwidth" in bb
        assert "percent_b" in bb

    def test_stochastic_result_structure(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        sto = result["stochastic"]
        assert "k" in sto
        assert "d" in sto

    def test_adx_result_structure(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        adx = result["adx"]
        assert "adx" in adx
        assert "di_plus" in adx
        assert "di_minus" in adx

    def test_rsi_in_valid_range(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        rsi = result["rsi"]
        if rsi is not None:
            assert 0.0 <= rsi <= 100.0

    def test_williams_r_in_valid_range(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        wr = result["williams_r"]
        if wr is not None:
            assert -100.0 <= wr <= 0.0

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError, match="candles must not be empty"):
            calculate_all_indicators(empty_candles)

    def test_small_candles_partial_results(self, btc_candles_10):
        """10개 캔들 — 일부 지표 None 허용."""
        result = calculate_all_indicators(btc_candles_10)
        # 핵심 키들은 존재해야 함
        assert "ema" in result
        assert "rsi" in result
        # Bollinger(20) > 10개 → None
        assert result["bollinger"]["upper"] is None
        assert result["bollinger"]["middle"] is None

    def test_returns_indicator_result_type(self, btc_candles_200):
        """반환값이 IndicatorResult 구조를 따르는지 확인."""
        result = calculate_all_indicators(btc_candles_200)
        assert isinstance(result, dict)

    def test_obv_is_float_or_none(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        obv = result["obv"]
        assert obv is None or isinstance(obv, float)

    def test_atr_positive(self, btc_candles_200):
        result = calculate_all_indicators(btc_candles_200)
        atr = result["atr"]
        if atr is not None:
            assert atr > 0.0
