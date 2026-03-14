"""변동성/거래량 지표 계산 모듈 — Bollinger Bands, ATR, ADX, OBV.

순수 계산 패키지 — FastAPI / DB / Redis 의존성 완전 금지.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .types import ADXResult, BollingerResult, CandleInput

logger = logging.getLogger(__name__)


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

def _to_series(candles: list[CandleInput], field: str) -> pd.Series:
    """CandleInput 리스트에서 단일 필드 Series 추출."""
    return pd.Series([c[field] for c in candles], dtype=float)


def _last_value(series: pd.Series) -> float | None:
    """Series 마지막 값 반환. NaN이면 None."""
    val = series.iloc[-1]
    return None if pd.isna(val) else float(val)


# ── Bollinger Bands ────────────────────────────────────────────────────────────

def calculate_bollinger_bands(
    candles: list[CandleInput],
    period: int = 20,
    std_dev: float = 2.0,
) -> BollingerResult:
    """Bollinger Bands + %B 계산. PRD §7.3.1 전략 D: %B < 0.05.

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        period: SMA 기간. 기본 20.
        std_dev: 표준편차 배수. 기본 2.0.

    Returns:
        BollingerResult: upper, middle, lower, bandwidth, percent_b.
            percent_b = (close - lower) / (upper - lower). 데이터 부족 시 None.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    _null: BollingerResult = {
        "upper": None,
        "middle": None,
        "lower": None,
        "bandwidth": None,
        "percent_b": None,
    }

    if not candles:
        raise ValueError("candles must not be empty")

    close = _to_series(candles, "close")
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=1)

    upper = sma + std_dev * std
    lower = sma - std_dev * std

    upper_val = _last_value(upper)
    middle_val = _last_value(sma)
    lower_val = _last_value(lower)

    if upper_val is None or middle_val is None or lower_val is None:
        return _null

    band_width = upper_val - lower_val
    bandwidth = band_width / middle_val if middle_val != 0 else None

    last_close = float(close.iloc[-1])
    if band_width != 0:
        percent_b = (last_close - lower_val) / band_width
    else:
        percent_b = None

    return BollingerResult(
        upper=upper_val,
        middle=middle_val,
        lower=lower_val,
        bandwidth=bandwidth,
        percent_b=percent_b,
    )


# ── ATR ────────────────────────────────────────────────────────────────────────

def calculate_atr(candles: list[CandleInput], period: int = 14) -> float | None:
    """ATR(Average True Range) 계산. Wilder's smoothing 사용.

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        period: ATR 기간. 기본 14.

    Returns:
        ATR 값. 데이터 부족 시 None.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    if not candles:
        raise ValueError("candles must not be empty")

    high = _to_series(candles, "high")
    low = _to_series(candles, "low")
    close = _to_series(candles, "close")

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Wilder's smoothing = EWM with alpha=1/period, adjust=False
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return _last_value(atr)


# ── ADX ────────────────────────────────────────────────────────────────────────

def calculate_adx(candles: list[CandleInput], period: int = 14) -> ADXResult:
    """ADX(Average Directional Index) 계산. +DI, -DI 포함.

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        period: ADX 기간. 기본 14.

    Returns:
        ADXResult: adx, di_plus, di_minus. 데이터 부족 시 None.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    _null: ADXResult = {"adx": None, "di_plus": None, "di_minus": None}

    if not candles:
        raise ValueError("candles must not be empty")

    high = _to_series(candles, "high")
    low = _to_series(candles, "low")
    close = _to_series(candles, "close")

    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # True Range
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Directional Movement
    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        dtype=float,
    )

    # Wilder's smoothing
    atr_s = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_dm_s = plus_dm.ewm(alpha=1 / period, adjust=False).mean()
    minus_dm_s = minus_dm.ewm(alpha=1 / period, adjust=False).mean()

    # +DI, -DI
    di_plus = 100 * plus_dm_s / atr_s.replace(0, float("nan"))
    di_minus = 100 * minus_dm_s / atr_s.replace(0, float("nan"))

    # DX, ADX
    dx_denom = (di_plus + di_minus).replace(0, float("nan"))
    dx = 100 * (di_plus - di_minus).abs() / dx_denom
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()

    adx_val = _last_value(adx)
    di_plus_val = _last_value(di_plus)
    di_minus_val = _last_value(di_minus)

    if adx_val is None and di_plus_val is None and di_minus_val is None:
        return _null

    return ADXResult(
        adx=adx_val,
        di_plus=di_plus_val,
        di_minus=di_minus_val,
    )


# ── OBV ────────────────────────────────────────────────────────────────────────

def calculate_obv(candles: list[CandleInput]) -> float | None:
    """OBV(On-Balance Volume) 계산. 최신 OBV 값 반환.

    OBV 초기값은 첫 캔들 기준 상대값 (절대값 의미 없음).

    Args:
        candles: OHLCV 캔들 데이터 리스트.

    Returns:
        최신 OBV 값. 캔들 1개 이상 필요.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    if not candles:
        raise ValueError("candles must not be empty")

    close = _to_series(candles, "close")
    volume = _to_series(candles, "volume")

    direction = pd.Series(
        np.where(
            close > close.shift(1),
            1,
            np.where(close < close.shift(1), -1, 0),
        ),
        dtype=float,
    )
    # 첫 캔들은 방향 없음 → 0으로 처리 (shift(1) NaN → direction=0)
    direction.iloc[0] = 0
    obv = (direction * volume).cumsum()
    return _last_value(obv)
