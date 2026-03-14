"""기술적 지표 테스트 픽스처."""
from __future__ import annotations

import math
import time

import pytest

from app.trading.indicators.types import CandleInput


def _make_candle(
    ts: float,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> CandleInput:
    return CandleInput(
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _sine_candles(n: int, base_ts: float | None = None) -> list[CandleInput]:
    """사인파 기반 합성 캔들 n개 생성 (1시간봉).

    가격이 사인파를 따르므로 지표 계산값이 수렴하며 유효 범위 내에 있음.
    """
    base = base_ts or 1_700_000_000.0
    interval = 3600.0  # 1시간
    candles: list[CandleInput] = []
    for i in range(n):
        t = base + i * interval
        mid = 50_000.0 + 5_000.0 * math.sin(2 * math.pi * i / 50)
        spread = 500.0
        candles.append(
            _make_candle(
                ts=t,
                open_=mid - spread / 2,
                high=mid + spread,
                low=mid - spread,
                close=mid + spread / 2 * math.cos(2 * math.pi * i / 30),
                volume=100.0 + 50.0 * abs(math.sin(2 * math.pi * i / 20)),
            )
        )
    return candles


@pytest.fixture
def btc_candles_200() -> list[CandleInput]:
    """BTC 1h 캔들 200개 — 모든 지표 정상 계산 가능."""
    return _sine_candles(200)


@pytest.fixture
def btc_candles_10() -> list[CandleInput]:
    """캔들 10개 — 대부분 지표 None 반환 케이스."""
    return _sine_candles(10)


@pytest.fixture
def btc_candles_1() -> list[CandleInput]:
    """캔들 1개."""
    return _sine_candles(1)


@pytest.fixture
def empty_candles() -> list[CandleInput]:
    """빈 리스트 — ValueError 케이스."""
    return []


@pytest.fixture
def today_candles() -> list[CandleInput]:
    """당일(KST 기준) 캔들만 있는 경우 — VWAP 정상 계산 확인."""
    # 오늘 KST 00:00 이후 UTC timestamp 계산
    now_utc = time.time()
    kst_offset = 9 * 3600
    kst_now = now_utc + kst_offset
    kst_day_start = kst_now - (kst_now % 86400)  # 오늘 KST 00:00 (seconds)
    utc_day_start = kst_day_start - kst_offset
    return _sine_candles(5, base_ts=utc_day_start)


@pytest.fixture
def monotone_rising_candles() -> list[CandleInput]:
    """단조 상승 캔들 30개 — OBV 양수 누적 확인."""
    base = 1_700_000_000.0
    candles: list[CandleInput] = []
    for i in range(30):
        price = 50_000.0 + i * 100.0
        candles.append(
            _make_candle(
                ts=base + i * 3600,
                open_=price,
                high=price + 50,
                low=price - 50,
                close=price + 10,
                volume=100.0,
            )
        )
    return candles
