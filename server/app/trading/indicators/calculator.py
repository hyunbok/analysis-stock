"""기술적 지표 통합 계산기.

순수 계산 패키지 — FastAPI / DB / Redis 의존성 완전 금지.
"""
from __future__ import annotations

import logging

from .oscillator import (
    calculate_cci,
    calculate_rsi,
    calculate_stochastic,
    calculate_williams_r,
)
from .trend import calculate_ema, calculate_macd, calculate_vwap
from .types import CandleInput, IndicatorResult
from .volatility import calculate_adx, calculate_atr, calculate_bollinger_bands, calculate_obv

logger = logging.getLogger(__name__)


def calculate_all_indicators(candles: list[CandleInput]) -> IndicatorResult:
    """모든 기술적 지표를 일괄 계산하여 반환.

    Args:
        candles: OHLCV 캔들 데이터 리스트. 시간순 정렬(오래된 것 먼저) 필수.
                 최소 200개 권장 (EMA-200 계산). 최소 1개 이상 필요.

    Returns:
        IndicatorResult: 11가지 지표 계산 결과. 데이터 부족한 지표는 None 반환.

    Raises:
        ValueError: candles가 비어있는 경우.

    Example:
        candles = [{"timestamp": 1700000000.0, "open": 50000.0, ...}, ...]
        result = calculate_all_indicators(candles)
        print(result["rsi"])  # 65.3
        print(result["macd"]["macd_line"])  # 123.45
    """
    if not candles:
        raise ValueError("candles must not be empty")

    return IndicatorResult(
        ema=calculate_ema(candles),
        vwap=calculate_vwap(candles),
        macd=calculate_macd(candles),
        rsi=calculate_rsi(candles),
        stochastic=calculate_stochastic(candles),
        williams_r=calculate_williams_r(candles),
        cci=calculate_cci(candles),
        bollinger=calculate_bollinger_bands(candles),
        atr=calculate_atr(candles),
        adx=calculate_adx(candles),
        obv=calculate_obv(candles),
    )
