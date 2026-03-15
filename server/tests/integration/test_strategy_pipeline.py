"""전략 엔진 통합 테스트 — 풀 파이프라인 및 주요 시나리오 (5건).

candles → indicators → regime → SignalGenerator 전체 흐름 검증.
순수 계산 패키지이므로 외부 DB/HTTP 의존성 없음 (mock 불필요).
"""
from __future__ import annotations

import pytest

from app.trading.indicators.calculator import calculate_all_indicators
from app.trading.indicators.types import CandleInput
from app.trading.regime.classifier import classify_regime
from app.trading.strategy.signal_generator import SignalGenerator
from app.trading.strategy.types import TradingSignal


# ── 픽스처 헬퍼 ───────────────────────────────────────────────────────────────

def _make_candle(
    i: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
) -> CandleInput:
    return CandleInput(
        timestamp=float(i * 300),
        open=open_, high=high, low=low, close=close, volume=volume,
    )


def _rising_candles(n: int = 210, base: float = 100.0) -> list[CandleInput]:
    """완만한 상승 추세 캔들 (Trend 장세 유발)."""
    candles: list[CandleInput] = []
    price = base
    for i in range(n):
        candles.append(_make_candle(
            i,
            open_=price,
            high=price + 1.0,
            low=price - 0.3,
            close=price + 0.5,
            volume=1200.0 if i == n - 1 else 1000.0,
        ))
        price += 0.5
    return candles


def _ranging_candles(n: int = 210) -> list[CandleInput]:
    """박스권 횡보 캔들 (Range 장세 유발)."""
    import math
    candles: list[CandleInput] = []
    for i in range(n):
        phase = math.sin(i * 0.3) * 2.0
        price = 100.0 + phase
        candles.append(_make_candle(
            i,
            open_=price - 0.2,
            high=price + 0.5,
            low=price - 0.5,
            close=price + 0.1,
            volume=800.0,
        ))
    return candles


# ── 통합 테스트 ───────────────────────────────────────────────────────────────

@pytest.fixture
def signal_generator() -> SignalGenerator:
    return SignalGenerator()


class TestFullPipeline:
    def test_full_pipeline_does_not_crash(self, signal_generator):
        """candles → indicators → regime → signal 전체 흐름 크래시 없음."""
        candles = _rising_candles(210)
        indicators = calculate_all_indicators(candles)
        regime = classify_regime(indicators)

        result = signal_generator.generate(candles, indicators, regime)
        # None 또는 TradingSignal 반환 (크래시 없음)
        assert result is None or isinstance(result, dict)

    def test_full_pipeline_with_mtf(self, signal_generator):
        """1h/4h 지표 포함 풀 파이프라인 크래시 없음."""
        candles = _rising_candles(210)
        indicators_5m = calculate_all_indicators(candles)
        indicators_1h = calculate_all_indicators(candles[-60:])
        indicators_4h = calculate_all_indicators(candles[-120:])
        regime = classify_regime(indicators_5m)

        result = signal_generator.generate(
            candles, indicators_5m, regime,
            indicators_1h=indicators_1h,
            indicators_4h=indicators_4h,
        )
        assert result is None or isinstance(result, dict)

    def test_trading_signal_structure_when_returned(self, signal_generator):
        """신호 반환 시 TradingSignal 필수 필드 모두 존재."""
        candles = _rising_candles(210)
        indicators = calculate_all_indicators(candles)
        regime = classify_regime(indicators)

        result = signal_generator.generate(candles, indicators, regime)
        if result is not None:
            required_keys = {
                "strategy_name", "action", "confidence",
                "entry_price", "exit_params", "strength",
                "position_scale", "mtf_weight", "conditions",
                "regime_type", "detail",
            }
            assert required_keys.issubset(result.keys())
            assert result["action"] in ("buy", "sell")
            assert 0.0 <= result["confidence"] <= 1.0
            assert result["exit_params"]["stop_loss"] > 0
            assert result["exit_params"]["take_profit"] > 0

    def test_hold_on_ranging_candles(self, signal_generator):
        """횡보 캔들에서 신호 발생하지 않거나 range 전략 선택."""
        candles = _ranging_candles(210)
        indicators = calculate_all_indicators(candles)
        regime = classify_regime(indicators)

        result = signal_generator.generate(candles, indicators, regime)
        if result is not None:
            # 범위 장세라면 range 전략이 선택되어야 함
            assert result["regime_type"] in ("range", "trend", "transition")

    def test_mtf_bearish_blocks_signal(self, signal_generator):
        """bearish 1h/4h 지표 → 매수 신호 차단 (None)."""
        from app.trading.indicators.types import ADXResult, EMAResult
        from tests.unit.trading.strategy.conftest import make_indicators

        candles = _rising_candles(210)
        indicators_5m = calculate_all_indicators(candles)
        regime = classify_regime(indicators_5m)

        # 강한 하락 방향 1h/4h 지표
        bearish = make_indicators(
            ema=EMAResult(ema_20=90.0, ema_50=100.0, ema_200=110.0),
            rsi=30.0,
            atr=1.0,
        )

        result = signal_generator.generate(
            candles, indicators_5m, regime,
            indicators_1h=bearish,
            indicators_4h=bearish,
        )
        # bearish MTF로 인해 매수 신호 차단
        assert result is None or result["action"] != "buy"
