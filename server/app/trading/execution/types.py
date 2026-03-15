"""주문 실행 엔진 타입 정의.

순수 타입 모듈 — FastAPI / SQLAlchemy / Beanie / Redis 의존성 없음.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, TypedDict

from app.trading.strategy.types import TradingSignal


# ── 리스크 파라미터 (AiTradingConfig에서 추출) ──────────────────────────────

class RiskParams(TypedDict):
    """리스크 파라미터 스냅샷.

    서비스 레이어에서 AiTradingConfig → RiskParams로 변환 후 주입.
    """

    max_investment_ratio: float     # 최대 투자비율 (기본 0.10)
    stop_loss_ratio: float          # 단일 손실 한도 (기본 0.02)
    take_profit_ratio: float        # 익절 비율 (기본 0.03)
    daily_max_loss_ratio: float     # 일일 손실 한도 (기본 0.05)
    max_active_positions: int       # 최대 동시 포지션 (기본 3)
    max_consecutive_losses: int     # 연속 손실 한도 (기본 3)
    mdd_limit_ratio: float          # MDD 한도 (기본 0.15)
    win_rate_estimate: float        # 승률 추정치 (기본 0.5, 향후 실적 기반)
    avg_rr_ratio: float             # 평균 RR 비율 (기본 1.5)


# ── 드로다운 상태 (Redis 저장/조회) ──────────────────────────────────────────

class DrawdownState(TypedDict):
    """드로다운 상태 스냅샷 — DrawdownManager에서 Redis Hash로 저장/조회."""

    daily_loss_ratio: float         # 오늘 누적 손실률 (총자산 대비)
    mdd_ratio: float                # 현재 MDD
    consecutive_losses: int         # 연속 손실 횟수
    is_suspended: bool              # 자동 중지 여부
    cooldown_until: str | None      # ISO datetime 또는 None
    peak_balance: float             # 최고 잔고 (MDD 계산용)
    detail: str


# ── 리스크 체크 결과 ─────────────────────────────────────────────────────────

class RiskCheckResult(TypedDict):
    """리스크 사전 검증 결과 — RiskManager.check() 출력."""

    allowed: bool                   # 거래 허용 여부
    reason: str                     # 거부 시 사유, 허용 시 "OK"
    daily_loss_ratio: float
    mdd_ratio: float
    consecutive_losses: int
    active_position_count: int


# ── 포지션 사이징 결과 ───────────────────────────────────────────────────────

class PositionSizeResult(TypedDict):
    """포지션 사이징 결과 — PositionSizer.calculate() 출력."""

    method: Literal["fixed_fractional", "half_kelly"]
    quantity: Decimal               # 주문 수량 (코인 단위)
    investment_amount: Decimal      # 투자 금액 (KRW)
    investment_ratio: float         # 총자산 대비 투자비율
    stop_loss_ratio: float          # 적용된 손절비율
    kelly_fraction: float | None    # HalfKelly 전용 (FF 시 None)
    strength_multiplier: float      # SignalStrength 배수 (1.0/0.75/0.5)
    position_scale: float           # regime confidence 기반 (1.0/0.5)
    detail: str


# ── 동적 손절/익절 ───────────────────────────────────────────────────────────

class StopLossParams(TypedDict):
    """최종 확정된 손절/익절 파라미터."""

    stop_loss_price: float
    take_profit_price: float
    stop_loss_atr_mult: float
    take_profit_atr_mult: float
    trailing_trigger_price: float   # 익절 50% 도달가 (Trailing Stop 활성화 기준)
    trailing_stop_distance: float   # ATR × 1.0 (Trailing Stop 추적 거리)


class TrailingStopState(TypedDict):
    """Trailing Stop 상태 (체결 후 모니터링용)."""

    is_active: bool
    peak_price: float               # 고점 (buy) 또는 저점 (sell)
    current_stop: float             # 현재 트레일링 스탑가
    activation_threshold: float     # 활성화 임계가 (익절 50% 도달 시)


# ── 실행 컨텍스트 ────────────────────────────────────────────────────────────

class TradeExecutionContext(TypedDict):
    """ExecutionEngine 실행에 필요한 컨텍스트.

    서비스 레이어에서 조립 후 주입.
    """

    user_id: str                    # UUID str
    exchange_account_id: str        # UUID str
    coin_id: str                    # UUID str
    market: str                     # 거래소 마켓 코드 (e.g. "KRW-BTC")
    symbol: str                     # 정규화 심볼 (e.g. "BTC/KRW")
    signal: TradingSignal           # v1-17 매매 신호
    risk_params: RiskParams         # AiTradingConfig에서 추출
    total_capital: Decimal          # 총 자산 (KRW)
    available_balance: Decimal      # 사용 가능 잔고 (KRW)


# ── 실행 결과 ────────────────────────────────────────────────────────────────

class ExecutionResult(TypedDict):
    """ExecutionEngine.execute() 반환 타입."""

    order_id: str | None            # UUID str (DB trade_orders.id), None=스킵
    exchange_order_id: str | None
    status: str                     # "filled" | "partial" | "open" | "failed" | "skipped"
    quantity: Decimal
    executed_quantity: Decimal
    executed_price: Decimal | None
    fee: Decimal
    position_size: PositionSizeResult | None
    risk_check: RiskCheckResult
    skipped_reason: str | None      # 리스크 체크 실패 시 사유
    detail: str
