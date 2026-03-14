"""기술적 지표 계산 엔진 입출력 타입 정의.

FastAPI / SQLAlchemy / Beanie 의존성 완전 금지.
"""
from __future__ import annotations

from typing import TypedDict

# ── 최소 캔들 수 상수 ──────────────────────────────────────────────────────────

MIN_CANDLES_EMA_200 = 200
MIN_CANDLES_EMA_50 = 50
MIN_CANDLES_EMA_20 = 20
MIN_CANDLES_MACD = 35          # slow(26) + signal(9)
MIN_CANDLES_RSI = 15           # period(14) + 1
MIN_CANDLES_STOCHASTIC = 14
MIN_CANDLES_BOLLINGER = 20
MIN_CANDLES_ATR = 15
MIN_CANDLES_ADX = 28           # period * 2
MIN_CANDLES_RECOMMENDED = 200  # calculate_all_indicators 권장 최솟값

# VWAP 밴드 계수 (PRD §7.3.1)
VWAP_BAND_K: float = 1.5


# ── 입력 타입 ──────────────────────────────────────────────────────────────────

class CandleInput(TypedDict):
    """OHLCV 캔들 입력 데이터.

    Decimal 대신 float 사용 — pandas 연산 효율을 위해.
    서비스 레이어에서 Decimal → float 변환 후 전달.
    """

    timestamp: float   # Unix timestamp (seconds, UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float


# ── 결과 타입 ──────────────────────────────────────────────────────────────────

class EMAResult(TypedDict):
    """EMA 계산 결과. PRD §7.3.1: 단기(20)/중기(50)/장기(200)."""

    ema_20: float | None
    ema_50: float | None
    ema_200: float | None


class MACDResult(TypedDict):
    """MACD 계산 결과."""

    macd_line: float | None       # MACD 선 (12 EMA - 26 EMA)
    signal_line: float | None     # Signal 선 (9 EMA of MACD)
    histogram: float | None       # MACD - Signal


class VWAPResult(TypedDict):
    """VWAP + 밴드 계산 결과. PRD §7.3.1: VWAP ± (k × σ), k=1.5."""

    vwap: float | None
    upper_band: float | None      # VWAP + 1.5 × σ (당일 가격 표준편차)
    lower_band: float | None      # VWAP - 1.5 × σ


class BollingerResult(TypedDict):
    """Bollinger Bands 계산 결과. PRD §7.3.1: %B 포함."""

    upper: float | None
    middle: float | None          # 20 SMA
    lower: float | None
    bandwidth: float | None       # (upper - lower) / middle
    percent_b: float | None       # (close - lower) / (upper - lower)


class StochasticResult(TypedDict):
    """Stochastic Oscillator 계산 결과."""

    k: float | None               # %K (fast)
    d: float | None               # %D (3 SMA of %K)


class ADXResult(TypedDict):
    """ADX 계산 결과."""

    adx: float | None
    di_plus: float | None         # +DI
    di_minus: float | None        # -DI


class IndicatorResult(TypedDict):
    """calculate_all_indicators() 반환 타입.

    Note:
        지표 값만 반환. 과매수/과매도 플래그(overbought/oversold)는 포함하지 않는다.
        RSI<30, Stochastic %K<20 등 조건 판별은 상위 레이어(regime/strategy 모듈)에서 담당.
        이 분리는 indicators/ 패키지의 순수성과 단일 책임을 유지하기 위한 설계 결정.
    """

    ema: EMAResult
    vwap: VWAPResult
    macd: MACDResult
    rsi: float | None
    stochastic: StochasticResult
    williams_r: float | None
    cci: float | None
    bollinger: BollingerResult
    atr: float | None
    adx: ADXResult
    obv: float | None
