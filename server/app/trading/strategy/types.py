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
