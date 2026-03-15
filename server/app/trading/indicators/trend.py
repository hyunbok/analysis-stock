"""추세 지표 계산 모듈 — EMA, VWAP, MACD.

순수 계산 패키지 — FastAPI / DB / Redis 의존성 완전 금지.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd

from .types import VWAP_BAND_K, CandleInput, EMAResult, MACDResult, VWAPResult

logger = logging.getLogger(__name__)

# KST = UTC+9 → KST 00:00 = UTC 15:00 전날
_KST_OFFSET_SECONDS = 9 * 3600


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

def _to_series(candles: list[CandleInput], field: str) -> pd.Series:
    """CandleInput 리스트에서 단일 필드 Series 추출."""
    return pd.Series([c[field] for c in candles], dtype=float)


def _last_value(series: pd.Series) -> float | None:
    """Series 마지막 값 반환. NaN이면 None."""
    val = series.iloc[-1]
    return None if pd.isna(val) else float(val)


# ── EMA ────────────────────────────────────────────────────────────────────────

def calculate_ema(candles: list[CandleInput], periods: list[int] = (20, 50, 200)) -> EMAResult:
    """EMA(Exponential Moving Average) 계산. PRD §7.3.1: 기본 20/50/200.

    Args:
        candles: OHLCV 캔들 데이터 리스트. 시간순 정렬(오래된 것 먼저) 필수.
        periods: 계산할 EMA 기간 리스트. 기본 [20, 50, 200].

    Returns:
        EMAResult: 각 period의 최신 EMA 값. 데이터 부족 시 None.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    if not candles:
        raise ValueError("candles must not be empty")

    close = _to_series(candles, "close")
    result: EMAResult = {"ema_20": None, "ema_50": None, "ema_200": None}

    period_map = {20: "ema_20", 50: "ema_50", 200: "ema_200"}
    for p in periods:
        key = period_map.get(p)
        if key is None:
            continue
        ema = close.ewm(span=p, adjust=False).mean()
        result[key] = _last_value(ema)

    return result


# ── VWAP ───────────────────────────────────────────────────────────────────────

def calculate_vwap(candles: list[CandleInput], k: float = VWAP_BAND_K) -> VWAPResult:
    """VWAP + 밴드 계산. PRD §7.3.1: VWAP ± (k × σ), k=1.5.

    당일 KST 00:00 (= UTC 15:00 전날) 기준 누적 VWAP. PRD §7.3.1 명세.
    캔들 timestamp 기반 KST 일 경계 감지.
    σ는 당일 캔들의 (고가+저가+종가)/3 타이피컬 프라이스 표준편차.

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        k: 밴드 폭 계수. 기본 1.5 (PRD 명세).

    Returns:
        VWAPResult: vwap, upper_band, lower_band. 당일 데이터 없으면 전체 None.
    """
    _null: VWAPResult = {"vwap": None, "upper_band": None, "lower_band": None}

    if not candles:
        raise ValueError("candles must not be empty")

    # 마지막 캔들의 KST 날짜 기준으로 당일 캔들 필터링
    last_ts = candles[-1]["timestamp"]
    last_kst = datetime.fromtimestamp(last_ts + _KST_OFFSET_SECONDS, tz=UTC)
    kst_day_start = last_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    # KST 00:00 → UTC timestamp
    day_start_utc_ts = kst_day_start.timestamp() - _KST_OFFSET_SECONDS

    today_candles = [c for c in candles if c["timestamp"] >= day_start_utc_ts]
    if not today_candles:
        return _null

    tp_list = [(c["high"] + c["low"] + c["close"]) / 3.0 for c in today_candles]
    vol_list = [c["volume"] for c in today_candles]

    tp = pd.Series(tp_list, dtype=float)
    vol = pd.Series(vol_list, dtype=float)

    total_volume = vol.sum()
    if total_volume == 0:
        return _null

    vwap_val = (tp * vol).sum() / total_volume

    # σ: 당일 타이피컬 프라이스 표준편차 (ddof=0)
    sigma = tp.std(ddof=0)
    if pd.isna(sigma):
        sigma = 0.0

    return VWAPResult(
        vwap=float(vwap_val),
        upper_band=float(vwap_val + k * sigma),
        lower_band=float(vwap_val - k * sigma),
    )


# ── MACD ───────────────────────────────────────────────────────────────────────

def calculate_macd(
    candles: list[CandleInput],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDResult:
    """MACD(Moving Average Convergence Divergence) 계산.

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        fast: 단기 EMA 기간. 기본 12.
        slow: 장기 EMA 기간. 기본 26.
        signal: Signal EMA 기간. 기본 9.

    Returns:
        MACDResult: macd_line, signal_line, histogram. 데이터 부족 시 None.

    Raises:
        ValueError: candles가 비어있는 경우.
    """
    if not candles:
        raise ValueError("candles must not be empty")

    close = _to_series(candles, "close")

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return MACDResult(
        macd_line=_last_value(macd_line),
        signal_line=_last_value(signal_line),
        histogram=_last_value(histogram),
    )
