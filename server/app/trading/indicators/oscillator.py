"""오실레이터 지표 계산 모듈 — RSI, Stochastic, Williams %R, CCI.

순수 계산 패키지 — FastAPI / DB / Redis 의존성 완전 금지.
"""
from __future__ import annotations

import logging

import pandas as pd

from .types import CandleInput, StochasticResult

logger = logging.getLogger(__name__)


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

def _to_series(candles: list[CandleInput], field: str) -> pd.Series:
    """CandleInput 리스트에서 단일 필드 Series 추출."""
    return pd.Series([c[field] for c in candles], dtype=float)


def _last_value(series: pd.Series) -> float | None:
    """Series 마지막 값 반환. NaN이면 None."""
    val = series.iloc[-1]
    return None if pd.isna(val) else float(val)


# ── RSI ────────────────────────────────────────────────────────────────────────

def calculate_rsi(candles: list[CandleInput], period: int = 14) -> float | None:
    """RSI(Relative Strength Index) 계산.

    Wilder's smoothing 방식 사용 (EWM alpha=1/period).

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        period: RSI 기간. 기본 14.

    Returns:
        0~100 사이 RSI 값. 데이터 부족 시 None.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    if not candles:
        raise ValueError("candles must not be empty")

    close = _to_series(candles, "close")
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return _last_value(rsi)


# ── Stochastic ─────────────────────────────────────────────────────────────────

def calculate_stochastic(
    candles: list[CandleInput],
    k_period: int = 14,
    d_period: int = 3,
) -> StochasticResult:
    """Stochastic Oscillator(%K, %D) 계산.

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        k_period: %K 기간. 기본 14.
        d_period: %D (SMA of %K) 기간. 기본 3.

    Returns:
        StochasticResult: k(%K), d(%D). 데이터 부족 시 None.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    _null: StochasticResult = {"k": None, "d": None}

    if not candles:
        raise ValueError("candles must not be empty")

    high = _to_series(candles, "high")
    low = _to_series(candles, "low")
    close = _to_series(candles, "close")

    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    denom = highest_high - lowest_low
    # 분모가 0인 경우 NaN 처리
    k_line = ((close - lowest_low) / denom.replace(0, float("nan"))) * 100
    d_line = k_line.rolling(window=d_period).mean()

    return StochasticResult(
        k=_last_value(k_line),
        d=_last_value(d_line),
    )


# ── Williams %R ────────────────────────────────────────────────────────────────

def calculate_williams_r(candles: list[CandleInput], period: int = 14) -> float | None:
    """Williams %R 계산. 범위: -100 ~ 0.

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        period: 계산 기간. 기본 14.

    Returns:
        -100~0 사이 값. 데이터 부족 시 None.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    if not candles:
        raise ValueError("candles must not be empty")

    high = _to_series(candles, "high")
    low = _to_series(candles, "low")
    close = _to_series(candles, "close")

    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    denom = highest_high - lowest_low
    wr = ((highest_high - close) / denom.replace(0, float("nan"))) * -100
    return _last_value(wr)


# ── CCI ────────────────────────────────────────────────────────────────────────

def calculate_cci(candles: list[CandleInput], period: int = 20) -> float | None:
    """CCI(Commodity Channel Index) 계산.

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        period: 계산 기간. 기본 20.

    Returns:
        CCI 값. 데이터 부족 시 None.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    if not candles:
        raise ValueError("candles must not be empty")

    high = _to_series(candles, "high")
    low = _to_series(candles, "low")
    close = _to_series(candles, "close")

    tp = (high + low + close) / 3.0
    sma_tp = tp.rolling(window=period).mean()
    # Mean Absolute Deviation
    mad = tp.rolling(window=period).apply(lambda x: (abs(x - x.mean())).mean(), raw=True)
    # CCI = (TP - SMA_TP) / (0.015 * MAD)
    cci = (tp - sma_tp) / (0.015 * mad.replace(0, float("nan")))
    return _last_value(cci)
