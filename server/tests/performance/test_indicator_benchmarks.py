"""지표 계산 벤치마크 — pytest-benchmark.

성능 기준 (설계서 ST6):
  - indicators 200행 계산: < 50ms
  - indicators 576행 계산: < 100ms
"""
from __future__ import annotations

import pytest

from app.trading.indicators.calculator import calculate_all_indicators
from app.trading.indicators.oscillator import (
    calculate_cci,
    calculate_rsi,
    calculate_stochastic,
    calculate_williams_r,
)
from app.trading.indicators.trend import calculate_ema, calculate_macd, calculate_vwap
from app.trading.indicators.volatility import (
    calculate_adx,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_obv,
)

pytestmark = pytest.mark.benchmark


# ── 통합 계산 벤치마크 ────────────────────────────────────────────────────────

class TestCalculateAllIndicators:
    def test_200_candles(self, benchmark, candles_200):
        """200개 캔들 전체 지표 계산 — 기준: < 50ms."""
        result = benchmark(calculate_all_indicators, candles_200)
        assert result is not None
        # 결과 구조 검증
        assert "rsi" in result
        assert "macd" in result
        assert "ema" in result
        # 성능 기준 검증: mean < 50ms (benchmark 활성화 시에만)
        if benchmark.stats:
            assert benchmark.stats["mean"] < 0.050, (
                f"200행 지표 계산이 50ms 초과: {benchmark.stats['mean'] * 1000:.1f}ms"
            )

    def test_576_candles(self, benchmark, candles_576):
        """576개 캔들 전체 지표 계산 — 기준: < 100ms."""
        result = benchmark(calculate_all_indicators, candles_576)
        assert result is not None
        if benchmark.stats:
            assert benchmark.stats["mean"] < 0.100, (
                f"576행 지표 계산이 100ms 초과: {benchmark.stats['mean'] * 1000:.1f}ms"
            )


# ── 개별 지표 벤치마크 ────────────────────────────────────────────────────────

class TestIndividualIndicators:
    def test_rsi_200(self, benchmark, candles_200):
        result = benchmark(calculate_rsi, candles_200)
        # 200개 캔들 → MIN_CANDLES_RSI(15) 이상이므로 항상 계산됨. 0~100 범위 검증.
        if result is not None:
            assert 0.0 <= result <= 100.0, f"RSI 범위 벗어남: {result}"

    def test_macd_200(self, benchmark, candles_200):
        result = benchmark(calculate_macd, candles_200)
        assert "macd_line" in result

    def test_ema_200(self, benchmark, candles_200):
        result = benchmark(calculate_ema, candles_200)
        assert "ema_20" in result
        assert "ema_50" in result
        assert "ema_200" in result

    def test_bollinger_200(self, benchmark, candles_200):
        result = benchmark(calculate_bollinger_bands, candles_200)
        assert "upper" in result

    def test_stochastic_200(self, benchmark, candles_200):
        result = benchmark(calculate_stochastic, candles_200)
        assert "k" in result

    def test_adx_200(self, benchmark, candles_200):
        result = benchmark(calculate_adx, candles_200)
        assert "adx" in result

    def test_atr_200(self, benchmark, candles_200):
        # atr는 float | None — 값 범위 무제한이므로 실행 성공만 검증
        benchmark(calculate_atr, candles_200)

    def test_vwap_200(self, benchmark, candles_200):
        result = benchmark(calculate_vwap, candles_200)
        assert "vwap" in result

    def test_obv_200(self, benchmark, candles_200):
        # obv는 float | None — 값 범위 무제한이므로 실행 성공만 검증
        benchmark(calculate_obv, candles_200)

    def test_cci_200(self, benchmark, candles_200):
        # cci는 float | None — 값 범위 무제한이므로 실행 성공만 검증
        benchmark(calculate_cci, candles_200)

    def test_williams_r_200(self, benchmark, candles_200):
        # williams_r는 float | None (범위: -100~0) — 실행 성공만 검증
        benchmark(calculate_williams_r, candles_200)
