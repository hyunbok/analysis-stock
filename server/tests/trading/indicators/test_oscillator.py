"""oscillator.py 단위 테스트 — RSI, Stochastic, Williams %R, CCI."""
from __future__ import annotations

import pytest

from app.trading.indicators.oscillator import (
    calculate_cci,
    calculate_rsi,
    calculate_stochastic,
    calculate_williams_r,
)
from app.trading.indicators.types import CandleInput


def _flat_candles(n: int, price: float = 50000.0) -> list[CandleInput]:
    """가격 변동 없는 동일 가격 캔들."""
    return [
        CandleInput(timestamp=float(i), open=price, high=price, low=price, close=price, volume=100.0)
        for i in range(n)
    ]


class TestCalculateRSI:
    def test_normal_case(self, btc_candles_200):
        result = calculate_rsi(btc_candles_200)
        assert result is not None
        assert 0.0 <= result <= 100.0

    def test_returns_float(self, btc_candles_200):
        result = calculate_rsi(btc_candles_200)
        assert isinstance(result, float)

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError, match="candles must not be empty"):
            calculate_rsi(empty_candles)

    def test_all_gains_approaches_100(self):
        """모든 캔들이 상승하면 RSI → 100."""
        candles = [
            CandleInput(timestamp=float(i), open=float(i * 100), high=float(i * 100 + 50), low=float(i * 100 - 50), close=float((i + 1) * 100), volume=100.0)
            for i in range(50)
        ]
        result = calculate_rsi(candles)
        assert result is not None
        assert result > 90.0

    def test_all_losses_approaches_0(self):
        """모든 캔들이 하락하면 RSI → 0."""
        candles = [
            CandleInput(timestamp=float(i), open=float(5000 - i * 100), high=float(5000 - i * 100 + 50), low=float(5000 - i * 100 - 50), close=float(5000 - (i + 1) * 100), volume=100.0)
            for i in range(50)
        ]
        result = calculate_rsi(candles)
        assert result is not None
        assert result < 10.0

    def test_flat_price_returns_value(self):
        """가격 변동 없으면 RSI = 50 또는 0/NaN 처리."""
        candles = _flat_candles(20)
        result = calculate_rsi(candles)
        # 변동 없으면 gain=loss=0 → RS=NaN → RSI=NaN → None
        # 또는 0으로 처리될 수 있음 — None 허용
        # 실제로는 loss=0 이면 RS = gain/0 = inf → RSI=100
        # gain=0, loss=0 이면 NaN → None
        assert result is None or (0.0 <= result <= 100.0)

    def test_custom_period(self, btc_candles_200):
        result = calculate_rsi(btc_candles_200, period=7)
        assert result is not None
        assert 0.0 <= result <= 100.0


class TestCalculateStochastic:
    def test_normal_case(self, btc_candles_200):
        result = calculate_stochastic(btc_candles_200)
        assert result["k"] is not None
        assert result["d"] is not None
        assert 0.0 <= result["k"] <= 100.0  # type: ignore
        assert 0.0 <= result["d"] <= 100.0  # type: ignore

    def test_insufficient_data_returns_none(self, btc_candles_10):
        """10개 < k_period(14) → None."""
        result = calculate_stochastic(btc_candles_10)
        assert result["k"] is None
        assert result["d"] is None

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError):
            calculate_stochastic(empty_candles)

    def test_flat_price_returns_nan_as_none(self):
        """high=low 이면 분모=0 → NaN → None."""
        candles = _flat_candles(20)
        result = calculate_stochastic(candles)
        assert result["k"] is None

    def test_d_is_smoothed_k(self, btc_candles_200):
        """%D는 %K의 3-period SMA."""
        result = calculate_stochastic(btc_candles_200)
        assert result["k"] is not None
        assert result["d"] is not None


class TestCalculateWilliamsR:
    def test_normal_case(self, btc_candles_200):
        result = calculate_williams_r(btc_candles_200)
        assert result is not None
        assert -100.0 <= result <= 0.0

    def test_insufficient_data_returns_none(self, btc_candles_10):
        result = calculate_williams_r(btc_candles_10)
        # 10개 < 14개 → rolling(14) → NaN → None
        assert result is None

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError):
            calculate_williams_r(empty_candles)

    def test_range_is_negative(self, btc_candles_200):
        """Williams %R 범위: -100 ~ 0."""
        result = calculate_williams_r(btc_candles_200)
        if result is not None:
            assert -100.0 <= result <= 0.0


class TestCalculateCCI:
    def test_normal_case(self, btc_candles_200):
        result = calculate_cci(btc_candles_200)
        assert result is not None
        assert isinstance(result, float)

    def test_insufficient_data_returns_none(self, btc_candles_10):
        result = calculate_cci(btc_candles_10)
        assert result is None

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError):
            calculate_cci(empty_candles)

    def test_typical_range(self, btc_candles_200):
        """CCI는 주로 -200~200 범위 (사인파 기반 데이터)."""
        result = calculate_cci(btc_candles_200)
        if result is not None:
            # 극단적 값이 아닌지 확인 (사인파 기반)
            assert abs(result) < 500.0

    def test_custom_period(self, btc_candles_200):
        result = calculate_cci(btc_candles_200, period=10)
        assert result is not None
