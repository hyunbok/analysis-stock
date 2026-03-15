# v1-17: AI 매매 전략 선택 및 신호 생성 엔진

> **Status**: Implemented (구현 완료, 코드 리뷰 통과, 48/48 테스트 통과)
> **Branch**: `feature/v1-17_ai-trading-strategy-signal-engine`
> **선행 태스크**: v1-15 (기술적 지표), v1-16 (장세 분류)
> **참조**: PRD §7.3.5, §7.4, §7.4.1, §7.4.2, §7.5.3, §7.7

---

## 1. 개요

장세 분류 결과(RegimeResult)를 기반으로 5가지 매매 전략 중 적합한 전략을 선택하고, 진입/청산 조건을 평가하여 매매 신호(TradingSignal)를 생성하는 순수 계산 엔진.

**핵심 파이프라인:**
```
candles(5m) → indicators → regime → strategy selector → signal generator → TradingSignal
                                                              ↑
                                                    indicators(1h, 4h) — MTF 검증
```

---

## 2. 패키지 구조

```
server/app/trading/strategy/
├── __init__.py              # public API exports
├── types.py                 # StrategyName, StrategySignal, ExitParams 등 타입
├── base.py                  # TradingStrategy ABC
├── candle_patterns.py       # 반전 캔들 패턴 감지 (해머, Engulfing, 도지 등)
├── trend_ma.py              # 전략 A: TrendMA 눌림목
├── vwap_bounce.py           # 전략 B: VWAP 눌림목
├── vwap_band_reversal.py    # 전략 C: VWAP 밴드 반전
├── rsi_bb_reversal.py       # 전략 D: RSI+볼밴+반전캔들 3중 조건
├── rsi_divergence.py        # 전략 E: RSI 다이버전스 + MACD
├── selector.py              # StrategySelector (regime → strategy 매핑)
└── signal_generator.py      # SignalGenerator + MTF 검증
```

**의존성 원칙**: `trading/strategy/`는 순수 계산 패키지 — FastAPI / DB / Redis import 금지. `trading/indicators/types.py`와 `trading/regime/types.py`만 의존.

### 2.1 __init__.py public exports

```python
"""매매 전략 엔진.

순수 계산 패키지 — FastAPI / DB / Redis 의존성 금지.
서비스 레이어에서는 SignalGenerator만 진입점으로 사용.
"""
from __future__ import annotations

from .signal_generator import SignalGenerator
from .types import (
    ConditionResult,
    ExitParams,
    MTFResult,
    StrategyName,
    StrategySelection,
    StrategySignal,
    TradingSignal,
)

__all__ = [
    # 진입점 (서비스 레이어에서 사용)
    "SignalGenerator",
    # 최종 출력 타입
    "TradingSignal",
    # 중간 타입 (서비스/로깅에서 참조)
    "StrategySignal",
    "StrategySelection",
    "ConditionResult",
    "ExitParams",
    "MTFResult",
    "StrategyName",
]
# Note: TradingStrategy ABC, 개별 전략 클래스, StrategySelector는 비공개.
# 서비스 → 전략 직접 접근 방지 (SignalGenerator를 통해서만 사용).
```

---

## 3. 타입 정의 (types.py)

```python
"""매매 전략 엔진 타입 정의.

FastAPI / SQLAlchemy / Beanie 의존성 완전 금지.
"""
from __future__ import annotations

from typing import Literal, TypedDict

from app.trading.regime.types import RegimeType


# ── 전략 타입 ─────────────────────────────────────────────────────────────────

StrategyName = Literal[
    "trend_ma",           # 전략 A: TrendMA 눌림목
    "vwap_bounce",        # 전략 B: VWAP 눌림목
    "vwap_band_reversal", # 전략 C: VWAP 밴드 반전
    "rsi_bb_reversal",    # 전략 D: RSI+볼밴+반전캔들
    "rsi_divergence",     # 전략 E: RSI 다이버전스+MACD
]

SignalStrength = Literal["strong", "moderate", "weak"]


# ── 조건 판별 결과 ─────────────────────────────────────────────────────────────

class ConditionResult(TypedDict):
    """개별 진입 조건 판별 결과.

    passed=True/False 모두 포함하여 "왜 confidence가 낮은지" 추적 가능.
    """

    name: str              # 조건 식별자 (예: "ema_aligned", "adx_gt_25")
    passed: bool           # 충족 여부
    detail: str            # 사람이 읽을 수 있는 설명 (예: "ADX=28.3 > 25")


# ── 청산 파라미터 ─────────────────────────────────────────────────────────────

class ExitParams(TypedDict):
    """ATR 기반 동적 손절/익절 파라미터."""

    stop_loss: float           # 손절가
    take_profit: float         # 익절가
    stop_loss_atr_mult: float  # 손절 ATR 배수 (로그/감사용)
    take_profit_atr_mult: float # 익절 ATR 배수
    risk_reward_ratio: float   # RR 비율


# ── 전략 평가 결과 ─────────────────────────────────────────────────────────────

class StrategySignal(TypedDict):
    """개별 전략 진입 조건 평가 결과."""

    strategy_name: StrategyName
    action: Literal["buy", "sell"]
    confidence: float          # 0.0 ~ 1.0 (조건 충족 강도)
    entry_price: float         # 진입가 (현재 종가)
    exit_params: ExitParams    # ATR 기반 손절/익절
    strength: SignalStrength   # 시그널 강도 (포지션 사이징 배수)
    conditions: list[ConditionResult]  # 전체 조건 (passed=True/False 포함)
    detail: str                # 사람이 읽을 수 있는 설명


# ── 전략 선택 결과 ─────────────────────────────────────────────────────────────

class StrategySelection(TypedDict):
    """StrategySelector가 반환하는 전략 선택 결과."""

    strategy_name: StrategyName
    position_scale: float      # 1.0 (풀) or 0.5 (보수적)
    reason: str                # 선택 근거


# ── MTF 검증 결과 ─────────────────────────────────────────────────────────────

class MTFDirection(TypedDict):
    """단일 타임프레임 방향 판별 결과."""

    timeframe: str             # "1h" or "4h"
    direction: Literal["bullish", "bearish", "neutral"]
    detail: str


class MTFResult(TypedDict):
    """멀티 타임프레임 검증 결과."""

    allowed: bool              # 거래 허용 여부
    weight: float              # 0.5 / 0.75 / 1.0
    directions: list[MTFDirection]
    detail: str


# ── 최종 매매 신호 ─────────────────────────────────────────────────────────────

class TradingSignal(TypedDict):
    """SignalGenerator 최종 출력 — 서비스 레이어에 전달."""

    strategy_name: StrategyName
    action: Literal["buy", "sell"]
    confidence: float          # regime confidence × strategy confidence × mtf weight
    entry_price: float
    exit_params: ExitParams
    strength: SignalStrength
    position_scale: float      # regime confidence 기반 (1.0 or 0.5)
    mtf_weight: float          # MTF 검증 가중치
    conditions: list[ConditionResult]  # 전체 조건 (passed=True/False 포함)
    regime_type: RegimeType    # Literal["trend", "range", "transition"]
    detail: str


# ── 캔들 패턴 ─────────────────────────────────────────────────────────────────

CandlePatternType = Literal[
    "hammer",
    "bullish_engulfing",
    "shooting_star",
    "bearish_engulfing",
    "doji",
]


class CandlePatternResult(TypedDict):
    """캔들 패턴 감지 결과."""

    pattern: CandlePatternType
    is_bullish: bool           # 상승 반전 패턴 여부
    detail: str
```

---

## 4. ABC 및 공통 유틸

### 4.1 TradingStrategy ABC (base.py)

```python
from __future__ import annotations

from abc import ABC, abstractmethod

from app.trading.indicators.types import CandleInput, IndicatorResult
from app.trading.regime.types import RegimeType

from .types import ExitParams, StrategyName, StrategySignal


class TradingStrategy(ABC):
    """매매 전략 기본 클래스.

    순수 계산 클래스 — DB / Redis / HTTP 의존성 없음.
    """

    @property
    @abstractmethod
    def name(self) -> StrategyName:
        """전략 식별자."""

    @property
    @abstractmethod
    def compatible_regimes(self) -> list[RegimeType]:
        """이 전략이 적용 가능한 장세 목록.

        StrategySelector가 1차 필터링에 사용.
        """

    @property
    @abstractmethod
    def stop_loss_atr_mult(self) -> float:
        """손절 ATR 배수 (PRD §7.5.3)."""

    @property
    @abstractmethod
    def take_profit_atr_mult(self) -> float:
        """익절 ATR 배수 (PRD §7.5.3)."""

    @property
    @abstractmethod
    def risk_reward_ratio(self) -> float:
        """목표 RR 비율."""

    @abstractmethod
    def evaluate(
        self,
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> StrategySignal | None:
        """진입 조건 평가.

        Args:
            candles: OHLCV 캔들 (시간순, 5분봉).
            indicators: 동일 캔들에 대한 기술적 지표 결과.

        Returns:
            조건 충족 시 StrategySignal, 미충족 시 None.

        Note:
            내부에서 전체 조건을 ConditionResult로 수집하되,
            모든 필수 조건 passed=True일 때만 StrategySignal 반환.
            미충족 시 None + logger.debug()로 어떤 조건이 실패했는지 기록.
        """

    def _build_exit_params(
        self,
        entry_price: float,
        atr: float,
        action: str,
    ) -> ExitParams:
        """ATR 기반 손절/익절 계산 헬퍼.

        공통 로직이므로 ABC에 제공.
        """
        if action == "buy":
            stop_loss = entry_price - atr * self.stop_loss_atr_mult
            take_profit = entry_price + atr * self.take_profit_atr_mult
        else:
            stop_loss = entry_price + atr * self.stop_loss_atr_mult
            take_profit = entry_price - atr * self.take_profit_atr_mult

        return ExitParams(
            stop_loss=stop_loss,
            take_profit=take_profit,
            stop_loss_atr_mult=self.stop_loss_atr_mult,
            take_profit_atr_mult=self.take_profit_atr_mult,
            risk_reward_ratio=self.risk_reward_ratio,
        )
```

### 4.2 반전 캔들 패턴 (candle_patterns.py)

PRD §7.4.2 기준 5가지 패턴 감지. 전략 B/C/D에서 공통 사용.

```python
"""반전 캔들 패턴 감지 유틸리티.

순수 함수 모듈 — 외부 의존성 없음.
PRD §7.4.2 기준 5가지 패턴 구현.
"""
from app.trading.indicators.types import CandleInput
from .types import CandlePatternResult, CandlePatternType


def detect_patterns(
    candles: list[CandleInput],
    *,
    bullish_only: bool = False,
    bearish_only: bool = False,
) -> list[CandlePatternResult]:
    """최근 2개 캔들에서 반전 패턴 감지.

    Args:
        candles: 최소 2개 캔들 (시간순).
        bullish_only: True면 상승 반전 패턴만 반환.
        bearish_only: True면 하락 반전 패턴만 반환.

    Returns:
        감지된 패턴 리스트 (없으면 빈 리스트).
    """
```

**패턴별 판별 로직:**

| 패턴 | 조건 | is_bullish |
|------|------|-----------|
| Hammer | 아래꼬리 ≥ 몸통×2, 위꼬리 ≤ 몸통×0.5, 몸통/전체범위 > 10% | True |
| Bullish Engulfing | 직전 음봉, 현재 양봉, 현재가 직전을 완전히 감싸는 패턴 | True |
| Shooting Star | 위꼬리 ≥ 몸통×2, 아래꼬리 ≤ 몸통×0.5 | False |
| Bearish Engulfing | 직전 양봉, 현재 음봉, 현재가 직전을 완전히 감싸는 패턴 | False |
| Doji | 몸통 ≤ 전체범위의 10% | context-dependent |

---

## 5. 전략별 상세 설계

### 5.1 전략 A: TrendMA 눌림목 (trend_ma.py)

**PRD §7.4.1 전략 A 기준.**

**진입 조건 (ALL 충족 필수):**
1. EMA20 > EMA50 > EMA200 (정배열)
2. ADX > 25, +DI > -DI
3. |가격 - EMA20| / EMA20 < 0.5% (EMA20 근접)
4. 현재봉 양봉 (close > open) — EMA20 반등
5. 거래량 ≥ 최근 20봉 평균 × 1.2
6. RSI 40~65

**ATR 파라미터:** 손절 1.5×ATR, 익절 3.0×ATR, RR 1:2

**구현 핵심:**
- 거래량 20봉 이동평균: `candles[-20:]`에서 직접 계산
- 양봉 판별: `candles[-1]["close"] > candles[-1]["open"]`
- EMA 근접: `abs(close - ema_20) / ema_20 < 0.005`

### 5.2 전략 B: VWAP 눌림목 (vwap_bounce.py)

**PRD §7.4.1 전략 B 기준.**

**진입 조건 (ALL 충족 필수):**
1. 가격 > VWAP
2. ADX > 20
3. |가격 - VWAP| / VWAP < 0.3% (VWAP 터치)
4. 반전 캔들 (해머 or Bullish Engulfing) — `candle_patterns.detect_patterns(bullish_only=True)`
5. RSI 40~65
6. OBV 상승 추세 — 현재 OBV > 5봉 전 OBV (candles 기반 직접 비교)

**ATR 파라미터:** 손절 1.5×ATR, 익절 3.0×ATR, RR 1:2

**OBV 상승 판별:** indicators에 최신 OBV 값만 있으므로, 과거 OBV 비교를 위해 candles[-5:]에서 간이 OBV 방향 계산 필요. 또는 indicators의 단일 OBV 값과 최근 close 방향으로 추정.

> **설계 결정**: OBV 추세 판별은 최근 5봉의 close 방향(상승 close 수 > 하락 close 수)과 현재 OBV 값의 부호로 간이 판별. 정밀한 OBV 시계열은 이 버전 범위 밖.

### 5.3 전략 C: VWAP 밴드 반전 (vwap_band_reversal.py)

**PRD §7.4.1 전략 C 기준.**

**진입 조건 (ALL 충족 필수):**
1. ADX < 20 (횡보 확인)
2. BB Bandwidth 수축 — `bandwidth < 0.05` (BB_NARROW_THRESHOLD)
3. 가격 ≤ VWAP 하단밴드 (lower_band)
4. 반전 캔들 패턴
5. RSI < 40
6. %B < 0.1

**ATR 파라미터:** 손절 1.0×ATR, 익절 1.5×ATR, RR 1:1.5

### 5.4 전략 D: RSI+볼밴+반전캔들 3중 조건 (rsi_bb_reversal.py)

**PRD §7.4.1 전략 D 기준.**

**진입 조건 (3조건 모두 동시 충족 필수):**
- **[조건 1]** RSI(14) < 30 AND Stochastic %K < 20
- **[조건 2]** 가격 ≤ BB Lower Band AND %B < 0.05
- **[조건 3]** 반전 캔들 (해머 / Bullish Engulfing / 도지 중 하나)

**ATR 파라미터:** 손절 1.0×ATR, 익절 1.5×ATR, RR 1:1.5~2.0

> 실제 RR은 1.5 적용 (보수적). PRD의 "1:1.5~2.0" 범위에서 하한값 채택.

### 5.5 전략 E: RSI 다이버전스 + MACD (rsi_divergence.py)

**PRD §7.4.1 전략 E 기준.**

**진입 조건 (ALL 충족 필수):**
1. RSI Bullish Divergence (최근 50캔들 탐색)
   - 가격 저점 ↓ (price_low_2 < price_low_1)
   - RSI 저점 ↑ (rsi_low_2 > rsi_low_1)
   - 두 저점 간격 ≥ 5캔들
2. MACD Golden Cross — MACD선이 Signal선 위로 돌파 + 히스토그램 음→양 전환
3. ADX < 25 또는 감소 중 (추세 약화 구간)
4. OBV 상승 전환

**ATR 파라미터:** 손절 1.5×ATR, 익절 3.75×ATR, RR 1:2.5

**RSI 다이버전스 감지 알고리즘:**
```
1. candles[-50:]에서 RSI 시계열 재계산 (또는 캔들별 RSI 히스토리 필요)
2. 가격 저점 찾기: 로컬 미니마 (양옆 2봉보다 낮은 점)
3. RSI 저점 찾기: 같은 인덱스의 RSI 값
4. 최근 2개 저점 비교: price↓ + RSI↑ = Bullish Divergence
```

> **설계 결정**: RSI 다이버전스 탐색에는 RSI 시계열이 필요. indicators/ 패키지의 `calculate_rsi()`는 최신 1개 값만 반환. 다이버전스 전략 내부에서 candles로부터 RSI 시계열을 직접 계산하는 헬퍼 `_calculate_rsi_series()` 구현 필요. indicators/oscillator.py의 내부 구현을 참조하되 복사는 최소화.

---

## 6. StrategySelector (selector.py)

### 6.1 매핑 로직

PRD §7.3.5 기반 confidence 구간별 처리:

```
Input:  RegimeResult + IndicatorResult + candles
Output: StrategySelection | None

1. confidence < 0.5 → return None (HOLD)
2. position_scale = 1.0 if confidence >= 0.7 else 0.5
3. regime에 따라 후보 전략 결정:
   - "trend"      → [TrendMA, VWAPBounce]
   - "range"      → [RSIBBReversal, VWAPBandReversal]
   - "transition" → [RSIDivergence]
4. 후보 전략을 순서대로 evaluate() 호출
   - 첫 번째 StrategySignal 반환 전략 채택 (우선순위 = 리스트 순서)
   - 전략 A/C 우선 (PRD: "둘 다 충족 시 TrendMA 우선", "RSI+볼밴 우선")
5. 모든 후보 미충족 → return None
```

### 6.2 매핑 상수

```python
# Regime → Strategy 우선순위 매핑 (PRD §7.4)
# 리스트 순서 = 우선순위 (둘 다 충족 시 앞 전략 채택)
REGIME_STRATEGY_MAP: dict[RegimeType, list[StrategyName]] = {
    "trend": ["trend_ma", "vwap_bounce"],           # TrendMA 우선
    "range": ["rsi_bb_reversal", "vwap_band_reversal"],  # RSI+볼밴 우선
    "transition": ["rsi_divergence"],
}
```

### 6.3 클래스 설계

```python
class StrategySelector:
    """regime → strategy 매핑 + 조건부 전략 선택.

    순수 계산 클래스 — DB / Redis / HTTP 의존성 없음.
    """

    def __init__(self) -> None:
        self._strategies: dict[StrategyName, TradingStrategy] = {
            "trend_ma": TrendMAStrategy(),
            "vwap_bounce": VWAPBounceStrategy(),
            "rsi_bb_reversal": RSIBBReversalStrategy(),
            "vwap_band_reversal": VWAPBandReversalStrategy(),
            "rsi_divergence": RSIDivergenceStrategy(),
        }

    def select(
        self,
        regime: RegimeResult,
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> tuple[StrategySelection, StrategySignal] | None:
        """전략 선택 + 진입 조건 평가.

        1. confidence < 0.5 → None (HOLD)
        2. REGIME_STRATEGY_MAP에서 후보 전략 조회
        3. 후보를 순서대로 evaluate() → 첫 번째 non-None 채택
        4. (StrategySelection, StrategySignal) 또는 None 반환

        Returns:
            (StrategySelection, StrategySignal) 또는 None (HOLD).
        """
```

---

## 7. SignalGenerator + MTF 검증 (signal_generator.py)

### 7.1 MTF (Multi-Timeframe) 방향 판별

1시간봉/4시간봉 각각의 IndicatorResult에서 방향 판별:

```
bullish 조건 (any):
  - EMA20 > EMA50 (상승 정렬)
  - RSI > 50
  - VWAP 위 가격 (1h만)

bearish 조건 (any):
  - EMA20 < EMA50 (하락 정렬)
  - RSI < 50

neutral: 위 조건 미충족 또는 혼합
```

### 7.2 MTF 검증 규칙 (PRD §7.7)

| 1h 방향 | 4h 방향 | allowed | weight |
|---------|---------|---------|--------|
| bullish | bullish | True    | 1.0    |
| bullish | neutral | True    | 0.75   |
| neutral | bullish | True    | 0.75   |
| neutral | neutral | True    | 0.5    |
| bearish | bearish | buy 차단 | 0.0   |
| bullish | bearish | buy 차단 | 0.0   |
| bearish | bullish | buy 차단 | 0.0   |

> **차단 규칙**: 매수 신호 시 반대 방향(bearish) 타임프레임이 있으면 차단. 매도는 반대로.

### 7.3 SignalGenerator 클래스

```python
class SignalGenerator:
    """매매 신호 생성 + MTF 검증.

    순수 계산 클래스 — DB / Redis / HTTP 의존성 없음.
    """

    def __init__(self) -> None:
        self._selector = StrategySelector()

    def generate(
        self,
        candles: list[CandleInput],
        indicators: IndicatorResult,
        regime: RegimeResult,
        indicators_1h: IndicatorResult | None = None,
        indicators_4h: IndicatorResult | None = None,
    ) -> TradingSignal | None:
        """매매 신호 생성.

        1. StrategySelector.select() → 전략 선택 + 진입 평가
        2. MTF 방향 검증 → 차단 or 가중치 적용
        3. 최종 confidence = regime.confidence × strategy.confidence × mtf.weight
        4. TradingSignal 조립

        Args:
            candles: 5분봉 OHLCV (시간순, 최소 200개 권장).
            indicators: 5분봉 기술적 지표.
            regime: 장세 분류 결과.
            indicators_1h: 1시간봉 지표 (MTF, 선택).
            indicators_4h: 4시간봉 지표 (MTF, 선택).

        Returns:
            TradingSignal 또는 None (HOLD / MTF 차단).
        """
```

### 7.4 시퀀스 다이어그램

```
Service Layer                    trading/strategy/
    │                                  │
    │  candles, indicators,            │
    │  regime, ind_1h, ind_4h          │
    │ ───────────────────────────────► │
    │                    SignalGenerator.generate()
    │                                  │
    │                          StrategySelector.select()
    │                                  │
    │                    ┌─────────────┤
    │                    │  confidence < 0.5?
    │                    │  → return None (HOLD)
    │                    │
    │                    │  regime="trend"
    │                    │  → TrendMA.evaluate()
    │                    │    → signal or None
    │                    │  → VWAPBounce.evaluate()
    │                    │    → signal or None
    │                    │
    │                    │  First non-None signal + selection
    │                    └─────────────┤
    │                                  │
    │                          _verify_mtf()
    │                    ┌─────────────┤
    │                    │  _classify_direction(ind_1h)
    │                    │  _classify_direction(ind_4h)
    │                    │
    │                    │  Both opposite? → return None (차단)
    │                    │  weight = 1.0 / 0.75 / 0.5
    │                    └─────────────┤
    │                                  │
    │                          Assemble TradingSignal
    │                          confidence = regime × strategy × mtf
    │                                  │
    │ ◄─────────────────────────────── │
    │        TradingSignal | None      │
```

---

## 8. 서비스 레이어 통합 및 향후 확장 (v1-18+)

> v1-17 범위는 `trading/strategy/` 순수 계산 패키지만. 서비스 레이어 통합은 이후 태스크.

### 8.1 향후 StrategyService (참고용)

```python
class StrategyService:
    def __init__(
        self,
        indicator_service: IndicatorService,
        regime_service: RegimeService,
        market_cache: MarketCacheService,
    ): ...

    async def analyze(
        self, exchange: str, market: str, user_id: str
    ) -> TradingSignal | None:
        # 1. 5m indicators (IndicatorService)
        # 2. regime (RegimeService)
        # 3. 1h/4h indicators (IndicatorService, parallel)
        # 4. SignalGenerator.generate()
        # 5. 캐시 + MongoDB 저장
        ...
```

### 8.2 청산 조건 평가 (향후 실행 엔진에서 구현)

v1-17에서는 진입 시점에 `ExitParams`(SL/TP 가격)를 계산하여 TradingSignal에 포함하는 것까지만 담당.
실시간 청산 조건 평가(Trailing Stop, 조건 반전 등)는 실행 엔진에서 포지션 상태 기반으로 구현.

```python
# 향후 SignalGenerator 확장 또는 별도 ExitEvaluator (참고용)
class ExitEvaluator:
    def evaluate_exit(
        self,
        active_signal: TradingSignal,   # 기존 진입 신호 (context)
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> ExitSignal | None:
        """청산 조건 평가. 충족 시 ExitSignal 반환."""
```

---

## 9. ATR 기반 손절/익절 파라미터 (PRD §7.5.3)

| 전략 | stop_loss_atr_mult | take_profit_atr_mult | RR |
|------|-------------------|---------------------|-----|
| TrendMA 눌림목 (A) | 1.5 | 3.0 | 1:2 |
| VWAP 눌림목 (B) | 1.5 | 3.0 | 1:2 |
| VWAP 밴드 반전 (C) | 1.0 | 1.5 | 1:1.5 |
| RSI+볼밴+반전캔들 (D) | 1.0 | 1.5 | 1:1.5 |
| RSI 다이버전스+MACD (E) | 1.5 | 3.75 | 1:2.5 |

---

## 10. 주요 상수 정리

```python
# ── 전략 공통 ──────────────────────────────────────────────
CONFIDENCE_HOLD_THRESHOLD = 0.5       # 미만 시 HOLD
CONFIDENCE_FULL_THRESHOLD = 0.7       # 이상 시 풀 포지션
CONSERVATIVE_POSITION_SCALE = 0.5     # 50~70% confidence

# ── 전략 A: TrendMA ──────────────────────────────────────
EMA_PROXIMITY_RATIO = 0.005           # |price - EMA20| / EMA20 < 0.5%
VOLUME_MA_PERIOD = 20                 # 거래량 이동평균 기간
VOLUME_MULTIPLIER = 1.2               # 거래량 ≥ 평균 × 1.2
TREND_MA_RSI_LOW = 40.0
TREND_MA_RSI_HIGH = 65.0
TREND_MA_ADX_MIN = 25.0

# ── 전략 B: VWAP 눌림목 ──────────────────────────────────
VWAP_PROXIMITY_RATIO = 0.003          # |price - VWAP| / VWAP < 0.3%
VWAP_BOUNCE_ADX_MIN = 20.0
VWAP_BOUNCE_RSI_LOW = 40.0
VWAP_BOUNCE_RSI_HIGH = 65.0
OBV_LOOKBACK = 5                      # OBV 상승 판별 lookback

# ── 전략 C: VWAP 밴드 반전 ────────────────────────────────
VWAP_BAND_ADX_MAX = 20.0
VWAP_BAND_BB_NARROW = 0.05            # BB Bandwidth 수축 기준
VWAP_BAND_RSI_MAX = 40.0
VWAP_BAND_PERCENT_B_MAX = 0.1

# ── 전략 D: RSI+볼밴 ─────────────────────────────────────
RSI_BB_RSI_MAX = 30.0
RSI_BB_STOCH_K_MAX = 20.0
RSI_BB_PERCENT_B_MAX = 0.05

# ── 전략 E: RSI 다이버전스 ────────────────────────────────
DIVERGENCE_LOOKBACK = 50              # RSI 다이버전스 탐색 캔들 수
DIVERGENCE_MIN_GAP = 5                # 두 저점 간 최소 간격
RSI_DIV_ADX_MAX = 25.0

# ── 캔들 패턴 ─────────────────────────────────────────────
HAMMER_LOWER_SHADOW_MULT = 2.0        # 아래꼬리 ≥ 몸통 × 2
HAMMER_UPPER_SHADOW_MULT = 0.5        # 위꼬리 ≤ 몸통 × 0.5
DOJI_BODY_RATIO = 0.1                 # 몸통 ≤ 전체범위 × 10%
MIN_BODY_RANGE_RATIO = 0.1            # 해머 몸통/전체범위 > 10%
```

---

## 11. 구현 파일 및 예상 코드량

| 파일 | 핵심 함수/클래스 | 예상 라인 |
|------|----------------|----------|
| `types.py` | 9개 TypedDict + 2개 Literal | ~130 |
| `base.py` | TradingStrategy ABC | ~60 |
| `candle_patterns.py` | detect_patterns, is_hammer, is_engulfing 등 | ~120 |
| `trend_ma.py` | TrendMAStrategy.evaluate() | ~100 |
| `vwap_bounce.py` | VWAPBounceStrategy.evaluate() | ~110 |
| `vwap_band_reversal.py` | VWAPBandReversalStrategy.evaluate() | ~100 |
| `rsi_bb_reversal.py` | RSIBBReversalStrategy.evaluate() | ~100 |
| `rsi_divergence.py` | RSIDivergenceStrategy.evaluate(), _find_divergence() | ~160 |
| `selector.py` | StrategySelector.select() | ~100 |
| `signal_generator.py` | SignalGenerator.generate(), _verify_mtf() | ~150 |
| `__init__.py` | public exports | ~30 |
| **합계** | | **~1,150** |

---

## 12. 테스트 전략

### 12.1 단위 테스트 (~65건)

| 대상 | 테스트 내용 | 건수 |
|------|-----------|------|
| `candle_patterns.py` | 5패턴 × (충족/미충족) + 경계값 | 12 |
| `trend_ma.py` | 6조건 개별 미충족 + 전체 충족 + 매도 조건 | 8 |
| `vwap_bounce.py` | 6조건 개별 미충족 + 전체 충족 | 8 |
| `vwap_band_reversal.py` | 6조건 개별 미충족 + 전체 충족 | 8 |
| `rsi_bb_reversal.py` | 3조건 그룹 미충족 + 전체 충족 | 6 |
| `rsi_divergence.py` | 다이버전스 감지 + MACD 크로스 + 전체 | 8 |
| `selector.py` | 3장세 × 조건 분기 + confidence 구간 + HOLD | 8 |
| `signal_generator.py` | MTF 조합(7가지) + 통합 흐름 | 7 |

### 12.2 통합 테스트 (~5건)

| 시나리오 | 설명 |
|---------|------|
| 풀 파이프라인 | candles → indicators → regime → signal 전체 흐름 |
| Trend 장세 TrendMA 선택 | 정배열 캔들 세트 → TrendMA 신호 발생 |
| Range 장세 RSI+볼밴 선택 | 과매도 캔들 세트 → RSI+BB 신호 발생 |
| MTF 차단 | bearish 1h/4h → 매수 차단 확인 |
| 모든 조건 미충족 HOLD | 애매한 지표 → None 반환 확인 |

---

## 13. 설계 결정 요약 (ADR)

### ADR-17-1: 순수 계산 패키지 유지
- **결정**: `trading/strategy/`는 FastAPI/DB/Redis 의존 금지
- **근거**: indicators/, regime/과 동일한 패턴 유지. 서비스 레이어 분리로 테스트 용이성 확보.

### ADR-17-2: StrategySignal에 ExitParams 내장
- **결정**: 손절/익절을 StrategySignal 내 ExitParams TypedDict로 포함
- **근거**: 전략별 ATR 배수가 다르므로(PRD §7.5.3) 전략 evaluate() 시점에 계산. 서비스 레이어에서 재계산 불필요.

### ADR-17-3: OBV 추세 간이 판별
- **결정**: indicators의 단일 OBV 값 + 최근 5봉 close 방향으로 간이 판별
- **근거**: indicators/ 패키지는 최신 단일값만 반환. OBV 시계열 캐싱은 v1-17 범위 초과.

### ADR-17-4: RSI 다이버전스 내부 RSI 시계열 계산
- **결정**: rsi_divergence.py 내부에 `_calculate_rsi_series()` 헬퍼 구현
- **근거**: indicators/oscillator.py의 `calculate_rsi()`는 최신 1개만 반환. 다이버전스는 50봉 RSI 시계열 필요. 내부 로직은 indicators의 RSI 알고리즘과 동일 (Wilder's smoothing).

### ADR-17-5: candle_patterns.py를 strategy/ 내 배치
- **결정**: `trading/strategy/candle_patterns.py` (indicators/ 아닌 strategy/ 내)
- **근거**: 캔들 패턴은 전략 평가 전용 유틸. indicators/는 수치 지표만 담당하는 설계 원칙 유지.

### ADR-17-6: StrategySelector가 evaluate()까지 호출
- **결정**: selector.select()가 전략 선택 + evaluate() 호출을 일괄 수행
- **근거**: "둘 다 충족 시 우선순위 전략 선택" 로직이 evaluate 결과에 의존. 분리하면 불필요한 2회 호출 발생.

### ADR-17-7: MTF 방향 판별 기준
- **결정**: EMA20 vs EMA50 + RSI 50 기준으로 bullish/bearish/neutral 분류
- **근거**: PRD §7.7에서 1h/4h의 "방향"을 명시했으나 구체적 기준 미정의. EMA 정렬 + RSI 중립선이 가장 직관적이고 indicators에서 바로 읽을 수 있음.

### ADR-17-8: ConditionResult로 전체 조건 추적 (code-architect 합의)
- **결정**: `conditions_met: list[str]` 대신 `conditions: list[ConditionResult]` (passed=True/False 포함)
- **근거**: 감사 추적 및 "왜 confidence가 낮은지" 분석 가능. RuleSignal 패턴(regime/)과 유사한 구조화된 결과.

### ADR-17-9: 청산 조건 평가 범위 (v1-17 밖)
- **결정**: v1-17은 진입 시점 ExitParams(SL/TP 가격) 계산까지만 포함. 실시간 청산 평가는 향후 실행 엔진에서 구현.
- **근거**: PRD 청산 로직(Trailing Stop, 조건 반전)은 포지션 상태 추적 필요 → 서비스/실행 레이어 책임.

### ADR-17-10: StrategyName Literal 타입 사용 (code-architect 합의)
- **결정**: `strategy_name: str` 대신 `StrategyName = Literal[...]` 타입 사용
- **근거**: 기존 `RegimeType = Literal[...]` 패턴과 일관성. mypy --strict 통과, IDE 자동완성 지원.

### ADR-17-11: SignalStrength "moderate" 사용 (code-architect 합의)
- **결정**: `"medium"` 대신 `"moderate"` 사용
- **근거**: code-architect 제안 수용. PRD §7.5.2에서 "Medium: ×0.75"로 표기하나, 코드에서는 더 정확한 "moderate" 채택.

### ADR-17-12: 5분봉이 전략 평가 기준 타임프레임 (PRD §7.7 확인)
- **결정**: 전략 evaluate()는 5분봉(Primary) 기준. 1h/4h는 MTF 방향 검증만.
- **근거**: PRD §7.7 명시 — "5분봉(Primary): 메인 진입 타임프레임". SignalGenerator 파라미터에서 `_5m` 접미사 생략 (기본이므로).

---

## 14. 의존성

### 기존 패키지 (신규 추가 없음)
- `trading/indicators/types.py`: CandleInput, IndicatorResult
- `trading/regime/types.py`: RegimeType, RegimeResult
- numpy/pandas: RSI 시계열 계산 시 indicators/ 내부 함수 참조

### 신규 외부 라이브러리: 없음
