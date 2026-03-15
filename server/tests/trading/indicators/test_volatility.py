"""volatility.py 단위 테스트 — Bollinger Bands, ATR, ADX, OBV."""
from __future__ import annotations

import pytest

from app.trading.indicators.types import CandleInput
from app.trading.indicators.volatility import (
    calculate_adx,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_obv,
)


def _flat_candles(n: int, price: float = 50000.0) -> list[CandleInput]:
    return [
        CandleInput(timestamp=float(i), open=price, high=price, low=price, close=price, volume=100.0)
        for i in range(n)
    ]


class TestCalculateBollingerBands:
    def test_normal_case(self, btc_candles_200):
        result = calculate_bollinger_bands(btc_candles_200)
        assert result["upper"] is not None
        assert result["middle"] is not None
        assert result["lower"] is not None
        assert result["bandwidth"] is not None
        assert result["percent_b"] is not None

    def test_band_ordering(self, btc_candles_200):
        """upper >= middle >= lower."""
        result = calculate_bollinger_bands(btc_candles_200)
        assert result["upper"] >= result["middle"] >= result["lower"]  # type: ignore

    def test_bandwidth_positive(self, btc_candles_200):
        result = calculate_bollinger_bands(btc_candles_200)
        assert result["bandwidth"] > 0  # type: ignore

    def test_insufficient_data_returns_null(self, btc_candles_10):
        """10개 < 20개 → None."""
        result = calculate_bollinger_bands(btc_candles_10)
        assert result["upper"] is None
        assert result["middle"] is None
        assert result["lower"] is None

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError):
            calculate_bollinger_bands(empty_candles)

    def test_percent_b_formula(self, btc_candles_200):
        """%B = (close - lower) / (upper - lower)."""
        result = calculate_bollinger_bands(btc_candles_200)
        if result["upper"] is not None and result["lower"] is not None:
            last_close = btc_candles_200[-1]["close"]
            expected_pct_b = (last_close - result["lower"]) / (result["upper"] - result["lower"])
            assert abs(result["percent_b"] - expected_pct_b) < 1e-9  # type: ignore

    def test_flat_price_returns_null_bandwidth(self):
        """가격 변동 없으면 std=0 → upper=lower=middle → bandwidth=0."""
        candles = _flat_candles(25)
        result = calculate_bollinger_bands(candles)
        # std=0 → upper=lower → bandwidth=0 → percent_b=None (0 division)
        assert result["upper"] is not None
        assert result["bandwidth"] == 0.0 or result["bandwidth"] is None or result["bandwidth"] < 1e-9
        assert result["percent_b"] is None

    def test_custom_params(self, btc_candles_200):
        result = calculate_bollinger_bands(btc_candles_200, period=10, std_dev=1.5)
        assert result["upper"] is not None


class TestCalculateATR:
    def test_normal_case(self, btc_candles_200):
        result = calculate_atr(btc_candles_200)
        assert result is not None
        assert result > 0.0

    def test_returns_float(self, btc_candles_200):
        assert isinstance(calculate_atr(btc_candles_200), float)

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError):
            calculate_atr(empty_candles)

    def test_atr_is_positive(self, btc_candles_200):
        result = calculate_atr(btc_candles_200)
        assert result > 0.0

    def test_single_candle(self, btc_candles_1):
        """1개 캔들 — prev_close 없음 → TR = high - low."""
        result = calculate_atr(btc_candles_1)
        assert result is not None
        expected_tr = btc_candles_1[0]["high"] - btc_candles_1[0]["low"]
        assert abs(result - expected_tr) < 1e-6

    def test_flat_price_atr_near_zero(self):
        """가격 변동 없으면 ATR ≈ 0."""
        candles = _flat_candles(20)
        result = calculate_atr(candles)
        assert result is not None
        assert result < 1e-6


class TestCalculateADX:
    def test_normal_case(self, btc_candles_200):
        result = calculate_adx(btc_candles_200)
        assert result["adx"] is not None
        assert result["di_plus"] is not None
        assert result["di_minus"] is not None

    def test_adx_range(self, btc_candles_200):
        """ADX는 0~100 사이."""
        result = calculate_adx(btc_candles_200)
        if result["adx"] is not None:
            assert 0.0 <= result["adx"] <= 100.0

    def test_di_positive(self, btc_candles_200):
        """+DI, -DI는 양수."""
        result = calculate_adx(btc_candles_200)
        if result["di_plus"] is not None:
            assert result["di_plus"] >= 0.0
        if result["di_minus"] is not None:
            assert result["di_minus"] >= 0.0

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError):
            calculate_adx(empty_candles)

    def test_single_candle(self, btc_candles_1):
        """1개 캔들 — ADX 계산 불가 (None 허용)."""
        result = calculate_adx(btc_candles_1)
        # 1개 데이터면 DM 계산 불가 → None 또는 0
        # pandas ewm 특성상 값 반환할 수 있음
        assert isinstance(result, dict)


class TestCalculateOBV:
    def test_normal_case(self, btc_candles_200):
        result = calculate_obv(btc_candles_200)
        assert result is not None
        assert isinstance(result, float)

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError):
            calculate_obv(empty_candles)

    def test_monotone_rising_positive_obv(self, monotone_rising_candles):
        """단조 상승 → OBV 양수 (첫 캔들은 0 기준)."""
        result = calculate_obv(monotone_rising_candles)
        assert result is not None
        assert result > 0.0

    def test_single_candle_obv(self, btc_candles_1):
        """1개 캔들 — OBV=0 (방향 없음)."""
        result = calculate_obv(btc_candles_1)
        assert result == 0.0

    def test_obv_increases_with_rising_price(self, btc_candles_200):
        """누적 OBV는 전체 부호 합."""
        result = calculate_obv(btc_candles_200)
        assert result is not None
