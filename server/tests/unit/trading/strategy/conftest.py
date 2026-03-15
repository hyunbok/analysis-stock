"""전략 엔진 테스트 공통 픽스처."""
from __future__ import annotations

import pytest

from app.trading.indicators.types import (
    ADXResult,
    BollingerResult,
    CandleInput,
    EMAResult,
    IndicatorResult,
    MACDResult,
    StochasticResult,
    VWAPResult,
)
from app.trading.regime.types import RegimeResult


def make_candle(
    i: int,
    *,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.5,
    volume: float = 1000.0,
) -> CandleInput:
    return CandleInput(
        timestamp=float(i * 300),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_candles(n: int, base_price: float = 100.0, rising: bool = True) -> list[CandleInput]:
    """단조 증가/감소하는 캔들 리스트 생성."""
    candles = []
    price = base_price
    for i in range(n):
        delta = 0.1 if rising else -0.1
        candles.append(make_candle(
            i,
            open_=price,
            high=price + 0.5,
            low=price - 0.5,
            close=price + delta,
            volume=1000.0,
        ))
        price += delta
    return candles


def make_indicators(**kwargs) -> IndicatorResult:
    """기본값(모두 None)에서 오버라이드 가능한 IndicatorResult 생성."""
    defaults = IndicatorResult(
        ema=EMAResult(ema_20=None, ema_50=None, ema_200=None),
        vwap=VWAPResult(vwap=None, upper_band=None, lower_band=None),
        macd=MACDResult(macd_line=None, signal_line=None, histogram=None),
        rsi=None,
        stochastic=StochasticResult(k=None, d=None),
        williams_r=None,
        cci=None,
        bollinger=BollingerResult(
            upper=None, middle=None, lower=None, bandwidth=None, percent_b=None
        ),
        atr=None,
        adx=ADXResult(adx=None, di_plus=None, di_minus=None),
        obv=None,
    )
    defaults.update(kwargs)
    return defaults


def make_regime(
    regime: str = "trend",
    confidence: float = 0.8,
) -> RegimeResult:
    return RegimeResult(
        regime=regime,  # type: ignore[arg-type]
        confidence=confidence,
        scores={"trend": confidence, "range": 0.1, "transition": 0.1},
        signals=[],
        gpt_validated=False,
        gpt_agreement=None,
    )
