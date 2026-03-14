# v1-15: 기술적 지표 계산 엔진 구현 설계서

> **작성**: code-architect + project-architect 공동 작성
> **최종 수정**: 2026-03-14
> **현재 상태**: 설계 확정

---

## 1. 개요

`server/app/trading/indicators/` 순수 함수 패키지를 구현한다.
FastAPI, SQLAlchemy, Beanie 등 인프라 의존성은 **완전 금지**. pandas 기반 계산, Redis 캐싱은 `MarketCacheService`를 통해 분리.

### 1.1 구현 지표 목록

| 분류 | 지표 | 파일 |
|------|------|------|
| Trend | EMA (20, 50, 200) | `trend.py` |
| Trend | VWAP + 밴드 (k=1.5) | `trend.py` |
| Trend | MACD (12, 26, 9) | `trend.py` |
| Oscillator | RSI (14) | `oscillator.py` |
| Oscillator | Stochastic (14, 3) | `oscillator.py` |
| Oscillator | Williams %R (14) | `oscillator.py` |
| Oscillator | CCI (20) | `oscillator.py` |
| Volatility | Bollinger Bands (20, 2.0) + %B | `volatility.py` |
| Volatility | ATR (14) | `volatility.py` |
| Volatility | ADX (14) | `volatility.py` |
| Volume | OBV | `volatility.py` (Volume 지표, 파일은 volatility.py에 통합) |

> **PRD §7.3.1 기준**: EMA는 단기(20)/중기(50)/장기(200) 3개. VWAP는 밴드(VWAP ± k×σ, k=1.5) 포함. Bollinger %B 포함.

---

## 2. 패키지 디렉토리 구조

```
server/app/trading/
├── __init__.py                 # 기존 빈 파일 유지
└── indicators/
    ├── __init__.py             # public API 노출: calculate_all_indicators, CandleInput
    ├── types.py                # TypedDict 입출력 타입 정의
    ├── trend.py                # EMA, VWAP, MACD
    ├── oscillator.py           # RSI, Stochastic, Williams %R, CCI
    ├── volatility.py           # Bollinger Bands, ATR, ADX, OBV
    └── calculator.py           # calculate_all_indicators() 통합 함수
```

### 2.1 디렉토리 원칙

- `trading/indicators/` 는 **독립 패키지** — `app.core`, `app.models`, `app.services` import 금지
- 허용 의존성: `pandas`, `numpy`, Python stdlib (`typing`, `math`, `logging`)
- `__init__.py` 는 public API만 노출 (`calculate_all_indicators`, `CandleInput`, `IndicatorResult`)

---

## 3. 타입 정의 (`types.py`)

```python
"""기술적 지표 계산 엔진 입출력 타입 정의.

FastAPI / SQLAlchemy / Beanie 의존성 완전 금지.
"""
from __future__ import annotations

from typing import TypedDict


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
    percent_b: float | None       # (close - lower) / (upper - lower), PRD 전략 D: %B < 0.05


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
```

---

## 4. 함수 시그니처 규격

### 4.1 `trend.py`

```python
import pandas as pd

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

def calculate_vwap(candles: list[CandleInput], k: float = 1.5) -> VWAPResult:
    """VWAP + 밴드 계산. PRD §7.3.1: VWAP ± (k × σ), k=1.5.

    당일 KST 00:00 (= UTC 15:00) 기준 누적 VWAP. PRD §7.3.1 명세.
    캔들 timestamp 기반 KST 일 경계 감지.
    σ는 당일 캔들의 (고가+저가+종가)/3 타이피컬 프라이스 표준편차.

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        k: 밴드 폭 계수. 기본 1.5 (PRD 명세).

    Returns:
        VWAPResult: vwap, upper_band, lower_band. 당일 데이터 없으면 전체 None.
    """

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
    """
```

### 4.2 `oscillator.py`

```python
def calculate_rsi(candles: list[CandleInput], period: int = 14) -> float | None:
    """RSI(Relative Strength Index) 계산.

    Wilder's smoothing 방식 사용 (EWM alpha=1/period).

    Args:
        candles: OHLCV 캔들 데이터 리스트.
        period: RSI 기간. 기본 14.

    Returns:
        0~100 사이 RSI 값. 데이터 부족 시 None.
    """

def calculate_stochastic(
    candles: list[CandleInput],
    k_period: int = 14,
    d_period: int = 3,
) -> StochasticResult:
    """Stochastic Oscillator(%K, %D) 계산."""

def calculate_williams_r(candles: list[CandleInput], period: int = 14) -> float | None:
    """Williams %R 계산. 범위: -100 ~ 0."""

def calculate_cci(candles: list[CandleInput], period: int = 20) -> float | None:
    """CCI(Commodity Channel Index) 계산."""
```

### 4.3 `volatility.py`

```python
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
    """

def calculate_atr(candles: list[CandleInput], period: int = 14) -> float | None:
    """ATR(Average True Range) 계산. Wilder's smoothing 사용."""

def calculate_adx(candles: list[CandleInput], period: int = 14) -> ADXResult:
    """ADX(Average Directional Index) 계산. +DI, -DI 포함."""

def calculate_obv(candles: list[CandleInput]) -> float | None:
    """OBV(On-Balance Volume) 계산. 최신 OBV 값 반환."""
```

### 4.4 `calculator.py` — 통합 함수

```python
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
```

---

## 5. 코드 컨벤션

### 5.1 공통 규칙

| 항목 | 규칙 |
|------|------|
| import 순서 | `from __future__ import annotations` 최상단 |
| 모듈 docstring | 파일 최상단 triple-quote, 순수 계산 패키지임을 명시 |
| logging | `logger = logging.getLogger(__name__)` 모듈 레벨 |
| 타입 어노테이션 | `list[CandleInput]`, `float \| None` (Python 3.10+ 스타일) |
| 네이밍 | snake_case 함수, UPPER_SNAKE 상수, PascalCase TypedDict |
| Docstring | Google 스타일 (Args:, Returns:, Raises:, Example:) |

### 5.2 pandas 사용 규칙

```python
# ✅ 올바른 패턴
import pandas as pd
import numpy as np

def _to_series(candles: list[CandleInput], field: str) -> pd.Series:
    """CandleInput 리스트에서 단일 필드 Series 추출."""
    return pd.Series([c[field] for c in candles], dtype=float)

# ✅ NaN 처리: iloc[-1] 이 NaN이면 None 반환
def _last_value(series: pd.Series) -> float | None:
    val = series.iloc[-1]
    return None if pd.isna(val) else float(val)
```

### 5.3 데이터 부족 처리 규칙

- **예외 금지**: 데이터 부족 시 `None` 반환 (ValueError는 빈 리스트일 때만)
- **최소 데이터**: 각 지표별 period 개수 미만이면 `None` 반환
- **NaN 전파**: pandas 자연 NaN 전파를 활용, 결과 추출 시 `_last_value()` 헬퍼로 변환

```python
# ✅ 올바른 패턴 — 데이터 부족 시 None
def calculate_rsi(candles: list[CandleInput], period: int = 14) -> float | None:
    if not candles:
        raise ValueError("candles must not be empty")
    close = _to_series(candles, "close")
    # period+1 미만이면 pandas가 자연스럽게 NaN 반환
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return _last_value(rsi)
```

### 5.4 순수성 검증 체크리스트

```
# indicators/ 패키지 내 금지 import 목록
- app.core.*
- app.models.*
- app.schemas.*
- app.services.*
- app.repositories.*
- fastapi
- sqlalchemy
- beanie
- motor
- redis (직접 사용 금지 — MarketCacheService 경유)
```

---

## 6. `__init__.py` public API

```python
"""기술적 지표 계산 엔진.

순수 함수 패키지 — FastAPI / DB 의존성 금지.
"""
from __future__ import annotations

from .calculator import calculate_all_indicators
from .types import CandleInput, IndicatorResult, VWAPResult

__all__ = [
    "calculate_all_indicators",
    "CandleInput",
    "IndicatorResult",
    "VWAPResult",
]
```

---

## 7. Redis 캐싱 규격

### 7.1 기존 인프라 활용

캐싱은 `trading/indicators/` 패키지 **외부** 에서 담당.
`MarketCacheService` 가 이미 `set_indicators` / `get_indicators` 구현됨.

```python
# MarketCacheService (기존 구현, 변경 없음)
async def set_indicators(self, exchange: str, market: str, timeframe: str, data: dict) -> None:
    ttl = RedisTTL.INDICATORS_SHORT if timeframe in _SHORT_TIMEFRAMES else RedisTTL.INDICATORS_LONG
    await self._redis.set(RedisKey.indicators(exchange, market, timeframe), ...)

async def get_indicators(self, exchange: str, market: str, timeframe: str) -> dict | None: ...
```

### 7.2 Redis 키/TTL 규격 (기존 redis_keys.py, 변경 없음)

| 키 패턴 | TTL | 비고 |
|---------|-----|------|
| `indicators:{exchange}:{market}:{timeframe}` | 60s (1m/3m/5m) | `INDICATORS_SHORT` |
| `indicators:{exchange}:{market}:{timeframe}` | 600s (1h+) | `INDICATORS_LONG` |

### 7.3 캐싱 적용 위치

```
[서비스 레이어 (IndicatorService)]
  1. MarketCacheService.get_indicators() 조회
  2. 캐시 HIT → 반환
  3. 캐시 MISS:
     a. MongoDB에서 캔들 조회 (Motor 직접)
     b. Decimal → float 변환 → CandleInput 변환
     c. calculate_all_indicators(candles) 호출
     d. MarketCacheService.set_indicators() 저장
     e. 결과 반환
```

### 7.4 IndicatorService (서비스 레이어 — indicators/ 외부)

```python
# server/app/services/indicator_service.py (신규)
class IndicatorService:
    """기술적 지표 계산 + Redis 캐싱 오케스트레이션."""

    def __init__(self, market_cache: MarketCacheService, db: AsyncIOMotorDatabase) -> None: ...

    async def get_indicators(
        self,
        exchange: str,
        market: str,
        timeframe: str,
        limit: int = 200,
    ) -> IndicatorResult:
        """캐시 우선 조회, MISS 시 MongoDB 캔들로 계산."""
```

---

## 8. 에러 처리 패턴

### 8.1 indicators/ 내부 (순수 Python 예외만)

```python
# ValueError만 사용 (AppError 금지)
raise ValueError("candles must not be empty")
raise ValueError(f"period must be positive, got {period}")
```

### 8.2 서비스 레이어 (AppError 변환)

`IndicatorErrors` 를 `core/exceptions.py` 에 추가:

```python
class IndicatorErrors:
    """기술적 지표 도메인 에러 팩토리."""

    @staticmethod
    def insufficient_candles(required: int, actual: int) -> AppError:
        return AppError(
            "INSUFFICIENT_CANDLES",
            f"지표 계산에 필요한 캔들이 부족합니다. 필요: {required}, 현재: {actual}",
            422,
        )

    @staticmethod
    def calculation_failed() -> AppError:
        return AppError(
            "INDICATOR_CALCULATION_FAILED",
            "지표 계산에 실패했습니다. 잠시 후 재시도해주세요.",
            500,
        )
```

---

## 9. 상수 정의

```python
# trading/indicators/types.py 에 포함

# 각 지표 최소 캔들 수 (None 반환 없이 정상 계산 가능한 최소치)
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
```

---

## 10. 테스트 구조

```
server/tests/trading/
└── indicators/
    ├── conftest.py             # 테스트 픽스처 (샘플 캔들 데이터)
    ├── test_trend.py           # EMA, VWAP, MACD 단위 테스트
    ├── test_oscillator.py      # RSI, Stochastic, Williams %R, CCI
    ├── test_volatility.py      # Bollinger Bands, ATR, ADX, OBV
    └── test_calculator.py      # calculate_all_indicators 통합 테스트
```

### 10.1 conftest.py 핵심 픽스처

```python
import pytest
from app.trading.indicators.types import CandleInput

@pytest.fixture
def btc_candles_200() -> list[CandleInput]:
    """BTC 1h 캔들 200개 — 모든 지표 정상 계산 가능."""
    ...

@pytest.fixture
def btc_candles_10() -> list[CandleInput]:
    """캔들 10개 — 대부분 지표 None 반환 케이스."""
    ...

@pytest.fixture
def empty_candles() -> list[CandleInput]:
    """빈 리스트 — ValueError 케이스."""
    return []
```

### 10.2 테스트 케이스 패턴

```python
class TestCalculateRSI:
    def test_normal_case(self, btc_candles_200):
        result = calculate_rsi(btc_candles_200)
        assert result is not None
        assert 0.0 <= result <= 100.0

    def test_insufficient_data_returns_none(self, btc_candles_10):
        result = calculate_rsi(btc_candles_10)
        assert result is None

    def test_empty_raises_value_error(self, empty_candles):
        with pytest.raises(ValueError):
            calculate_rsi(empty_candles)

    def test_known_value(self):
        """알려진 입력으로 기대값 검증."""
        # 수동 계산값과 비교
        ...
```

---

## 11. 구현 순서 (서브태스크 매핑)

| ST | 작업 | 파일 | 선행 |
|----|------|------|------|
| ST1 | 패키지 기본 구조 + 타입 정의 | `indicators/__init__.py`, `types.py` | — |
| ST2 | EMA 구현 | `trend.py` | ST1 |
| ST3 | VWAP, MACD 구현 | `trend.py` | ST1, ST2 |
| ST4 | RSI 구현 | `oscillator.py` | ST1 |
| ST5 | Stochastic, Williams %R, CCI | `oscillator.py` | ST1, ST4 |
| ST6 | Bollinger Bands, ATR | `volatility.py` | ST1 |
| ST7 | ADX 구현 | `volatility.py` | ST1, ST6 |
| ST8 | OBV 구현 | `volatility.py` | ST1, ST2 |
| ST9 | calculate_all_indicators | `calculator.py` | ST2~ST8 |
| ST10 | Redis 캐싱 레이어 + IndicatorService | `services/indicator_service.py` | ST9 |

---

## 12. 의존성 그래프 (모듈 레벨)

```
trading/indicators/calculator.py
  └── trend.py (calculate_ema, calculate_vwap, calculate_macd)
  └── oscillator.py (calculate_rsi, calculate_stochastic, ...)
  └── volatility.py (calculate_bollinger_bands, calculate_atr, calculate_adx, calculate_obv)
  └── types.py (CandleInput, IndicatorResult, ...)

services/indicator_service.py (FastAPI 레이어)
  └── trading/indicators/__init__.py (calculate_all_indicators, CandleInput)
  └── services/market_cache_service.py (get/set_indicators)
  └── core/redis_keys.py (RedisKey, RedisTTL)
  └── core/exceptions.py (IndicatorErrors ← 추가 예정)
```

---

## 13. 설계 결정 사항 로그

| # | 항목 | 결정 | 근거 |
|---|------|------|------|
| 1 | EMA 기간 | 20 / 50 / 200 | PRD §7.3.1 명세 (9/21 제외) |
| 2 | VWAP 반환 타입 | `VWAPResult` (vwap + upper_band + lower_band) | PRD §7.3.1 밴드 필요, 전략 C 사용 |
| 3 | VWAP 밴드 계수 | k=1.5 | PRD §7.3.1 명시 |
| 4 | VWAP 일 기준 | KST 00:00 (UTC 15:00) 리셋 | PRD §7.3.1 "당일 KST 00:00 기준 리셋" 명시 |
| 5 | Bollinger %B | `percent_b` 필드 추가 | PRD 전략 D: "%B < 0.05" 조건 |
| 6 | OBV 파일 위치 | `volatility.py` 통합 유지 | 파일 수 최소화, 5개 파일로 충분 |
| 7 | 과매수/과매도 플래그 | indicators/ 미포함 | SRP: 조건 판별은 regime/strategy 레이어 |
| 8 | 입력 타입 | `float` (Decimal 아님) | pandas 효율, 서비스 레이어에서 변환 |
| 9 | 데이터 부족 처리 | `None` 반환 (예외 아님) | 호출부 분기 처리 용이 |
| 10 | 병렬 실행 | 순차 실행 | pandas GIL 내 동작, 병렬화 불필요 |
| 11 | OBV 초기값 | 첫 캔들 기준 상대값 | 절대값 의미 없음 |
| 12 | `IndicatorService` API 노출 | v1-15 범위 외 | v1-16(AI 트레이딩)에서 결정 |

---

## 14. 성능 기준 (비기능 요구사항)

| 시나리오 | 목표 | 비고 |
|---------|------|------|
| `calculate_all_indicators(200행)` | < 50ms | 단일 코인 기본 케이스 |
| `calculate_all_indicators(576행)` | < 100ms | 2일 5분봉 (AI 매매 입력) |
| Redis 캐시 HIT 시 응답 | < 5ms | JSON deserialize 포함 |

> AI 매매 Celery 태스크가 5분 주기로 복수 코인을 처리하므로, 단일 코인 지표 계산이 100ms 이내여야 5분 윈도우 내 완료 보장.

---

## 15. 향후 연동 방향 (v1-15 범위 외)

```python
# v1-16 (장세 분석): IndicatorResult → RegimeDetector 입력
# RegimeDetector.detect(indicators: IndicatorResult, candles: list[CandleInput]) → RegimeResult

# v1-17 (전략 선택): IndicatorResult + RegimeResult → StrategySelector 입력
# StrategySelector.evaluate(regime: RegimeResult, indicators: IndicatorResult) → TradeSignal
```

---

## 현재 상태: 구현 완료 (2026-03-14)

- 모든 서브태스크(ST1~ST10) 구현 완료
- 77개 테스트 통과 (0.08s)
- ruff check 통과
- code-review-expert 리뷰 승인 (ruff 4건 수정 반영)
- 신규 의존성: pandas>=2.2, numpy>=1.26

*이 문서는 code-architect 초안 작성, project-architect 리뷰/보완 후 확정. (2026-03-14)*
