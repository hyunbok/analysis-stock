# v1-18: 주문 실행 및 리스크 관리 엔진

> **Status**: Implemented (구현 완료, 코드 리뷰 통과, 66/66 테스트 통과)
> **Branch**: `feature/v1-18_order-execution-risk-management-engine`
> **선행 태스크**: v1-14 (주문 실행 API), v1-15 (기술적 지표), v1-16 (장세 분류), v1-17 (전략 엔진)
> **참조**: PRD §7.5, §7.6, §7.8

---

## 1. 개요

v1-17 SignalGenerator가 생성한 TradingSignal을 받아 리스크 검증 → 포지션 사이징 → 주문 실행 → 상태 추적 → 로깅까지 자동화하는 실행 엔진.

**v1-15~17과의 핵심 차이점**: 이 패키지는 **순수 계산이 아님** — Redis(드로다운 상태), MongoDB(거래 로그), ExchangeProvider(주문 실행), PG AsyncSession(TradeOrder)에 의존.

**의존 방향 원칙**: `api → services → trading/` (단방향). ExecutionEngine은 `services/order_service.py`를 import하지 않음 — OrderRepository + Provider 직접 주입 (ADR-18-2).

**핵심 파이프라인:**
```
TradingSignal (v1-17)
  → DrawdownManager.get_state()    # Redis에서 드로다운 상태 조회
  → RiskManager.check()            # 리스크 사전 검증 (순수 계산)
  → PositionSizer.calculate()      # Fixed Fractional + Half-Kelly (순수 계산)
  → DynamicStopLoss.calculate()    # SL/TP + Trailing Stop (순수 계산)
  → Provider.place_order()         # 거래소 직접 주문 (Provider 주입)
  → OrderTracker.create_order()    # PG TradeOrder 저장 + 상태 추적
  → TradeLogger.log_entry()        # MongoDB trade_logs 기록
  → DrawdownManager.record_trade() # 드로다운 업데이트 (Redis)
```

---

## 2. 패키지 구조

```
server/app/trading/execution/
├── __init__.py              # public API exports
├── types.py                 # RiskParams, PositionSizeResult, ExecutionResult 등 TypedDict
├── constants.py             # 리스크 파라미터 상수
├── exceptions.py            # TradeExecutionError, RiskLimitExceeded 등 내부 예외
├── risk_manager.py          # RiskManager: 순수 리스크 체크 (DrawdownState + RiskParams 입력)
├── position_sizing.py       # FixedFractionalSizer + HalfKellySizer (독립 클래스, 순수)
├── sl_tp.py                 # DynamicStopLoss: ATR 기반 SL/TP + Trailing Stop (순수)
├── drawdown_manager.py      # DrawdownManager: Redis 상태 저장/조회 (async)
├── order_tracker.py         # OrderTracker: PG TradeOrder 생성 + 부분 체결 추적 (async)
├── trade_logger.py          # TradeLogger: MongoDB trade_logs 기록 (async)
└── engine.py                # ExecutionEngine: 오케스트레이터 (async)
```

**의존성 분류:**

| 모듈 | 순수/비순수 | 의존성 |
|------|----------|--------|
| types.py | 순수 타입 | strategy/types.py만 |
| constants.py | 순수 상수 | 없음 |
| exceptions.py | 순수 예외 | 없음 |
| risk_manager.py | **순수 계산** | types.py, constants.py만 |
| position_sizing.py | **순수 계산** | types.py, constants.py만 |
| sl_tp.py | **순수 계산** | types.py, constants.py만 |
| drawdown_manager.py | async | Redis |
| order_tracker.py | async | OrderRepository, ExchangeRestProvider |
| trade_logger.py | async | Beanie Document 직접 (주입 없음) |
| engine.py | async | 위 전체 모듈 조합 |

### 2.1 __init__.py public exports

```python
"""주문 실행 및 리스크 관리 엔진.

v1-15~17과 달리 순수 계산 패키지가 아님.
Redis(드로다운 상태), MongoDB(거래 로그), ExchangeProvider(주문)에 의존.
서비스 레이어(services/)에서 ExecutionEngine만 진입점으로 사용.
"""
from __future__ import annotations

from .engine import ExecutionEngine
from .types import (
    DrawdownState,
    ExecutionResult,
    PositionSizeResult,
    RiskCheckResult,
    RiskParams,
    TradeExecutionContext,
    TrailingStopState,
)

__all__ = [
    "ExecutionEngine",
    "DrawdownState",
    "ExecutionResult",
    "PositionSizeResult",
    "RiskCheckResult",
    "RiskParams",
    "TradeExecutionContext",
    "TrailingStopState",
]
```

---

## 3. 타입 정의 (types.py)

```python
"""주문 실행 엔진 타입 정의.

순수 타입 모듈 — FastAPI / SQLAlchemy / Beanie / Redis 의존성 없음.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, TypedDict

from app.trading.strategy.types import SignalStrength, StrategyName, TradingSignal


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
```

---

## 4. 내부 예외 (exceptions.py)

```python
"""실행 엔진 내부 예외.

trading/execution/ 패키지 전용. 서비스 레이어에서 catch 후 AppError로 변환.
providers/exceptions.py ↔ core/exceptions.py ExchangeErrors 패턴과 동일한 이중 레이어.
"""
from __future__ import annotations

from .types import DrawdownState


class TradeExecutionError(Exception):
    """실행 엔진 기본 예외."""


class RiskLimitExceeded(TradeExecutionError):
    """리스크 한도 초과 (daily_loss, mdd, consecutive_losses, max_positions).

    engine.py에서 catch하여 ExecutionResult(status="skipped") 반환.
    """

    def __init__(self, reason: str, state: DrawdownState) -> None:
        self.reason = reason
        self.state = state
        super().__init__(reason)


class PositionSizingError(TradeExecutionError):
    """포지션 사이징 실패 (잔고 부족, 최소 주문 미달 등)."""


class OrderExecutionError(TradeExecutionError):
    """주문 실행 실패 (거래소 오류 래핑)."""

    def __init__(self, reason: str, exchange_error: Exception | None = None) -> None:
        self.reason = reason
        self.exchange_error = exchange_error
        super().__init__(reason)
```

> **설계 결정 (ADR-18-9)**: 내부 예외는 `trading/execution/exceptions.py`에 배치. `core/exceptions.py`에 ExecutionErrors AppError 팩토리는 v1-18에서 추가하지 않음 — API 엔드포인트가 없으므로. 향후 API 노출 시 providers/exceptions.py → ExchangeErrors 패턴으로 이중 레이어 추가.

---

## 5. 리스크 파라미터 상수 (constants.py)

```python
"""리스크 관리 상수 (PRD §7.5, §7.6).

기본값 — 실제 동작은 RiskParams(AiTradingConfig에서 추출)에 의존.
PositionSizer, DynamicStopLoss에서 fallback으로 참조.
"""

# ── 리스크 한도 (기본값) ─────────────────────────────────────────────────────

DEFAULT_MAX_SINGLE_LOSS_RATIO = 0.02     # 단일 손실 한도 2%
DEFAULT_DAILY_MAX_LOSS_RATIO = 0.05      # 일일 손실 한도 5%
DEFAULT_MDD_LIMIT_RATIO = 0.15           # 최대 낙폭 한도 15%
DEFAULT_MAX_ACTIVE_POSITIONS = 3         # 최대 동시 포지션
DEFAULT_MAX_INVESTMENT_RATIO = 0.10      # 단일 투자비율 한도 10%
DEFAULT_MAX_CONSECUTIVE_LOSSES = 3       # 연속 손실 한도

# ── 포지션 사이징 ────────────────────────────────────────────────────────────

KELLY_HALF_FACTOR = 0.5                  # Half-Kelly = Kelly × 0.5
DEFAULT_WIN_RATE = 0.5                   # 초기 승률 추정치
DEFAULT_RR_RATIO = 1.5                   # 초기 RR 비율 추정치

# ── 신호 강도 배수 (PRD §7.5.2) ──────────────────────────────────────────────

SIGNAL_MULTIPLIER: dict[str, float] = {
    "strong": 1.0,
    "moderate": 0.75,
    "weak": 0.5,
}

# ── Trailing Stop (PRD §7.6) ────────────────────────────────────────────────

TRAILING_TRIGGER_RATIO = 0.5             # 익절 50% 도달 시 활성화
TRAILING_STOP_ATR_MULT = 1.0             # ATR × 1.0 추적 거리

# ── 쿨다운 ───────────────────────────────────────────────────────────────────

COOLDOWN_SECONDS = 4 * 3600              # 연속 손실 후 4시간 쿨다운

# ── 부분 체결 ────────────────────────────────────────────────────────────────

PARTIAL_FILL_WAIT_SECONDS = 60           # 부분 체결 대기 시간
PARTIAL_FILL_POLL_INTERVAL = 10          # 상태 확인 간격 (초)

# ── 재시도 ───────────────────────────────────────────────────────────────────

MAX_RETRY_COUNT = 2                      # 최대 재시도 횟수 (총 3회 시도)
RETRY_INTERVAL_SECONDS = 30              # 재시도 간격 (초)

# ── Redis ────────────────────────────────────────────────────────────────────

DRAWDOWN_HASH_TTL = 48 * 3600            # 48시간 (Hash TTL)
POSITIONS_SET_TTL = 24 * 3600            # 24시간 (열린 포지션 Set TTL)
```

---

## 6. 모듈별 상세 설계

### 6.1 RiskManager (risk_manager.py) — 순수 계산

DrawdownState + RiskParams를 입력받아 거래 허용 여부를 판정하는 **순수 계산 클래스**. Redis/DB 의존 없음.

```python
"""리스크 관리자 — 거래 사전 검증.

순수 계산 — Redis/DB 의존 없음.
DrawdownState(현재 상태) + RiskParams(한도) 입력 → RiskCheckResult 출력.
"""
from __future__ import annotations

from .types import DrawdownState, RiskCheckResult, RiskParams


class RiskManager:
    """리스크 사전 검증 — 순수 계산.

    검증 순서:
    1. 쿨다운 확인 (연속 손실 후 4시간)
    2. 일일 손실 한도 (기본 5%)
    3. MDD 한도 (기본 15%)
    4. 동시 포지션 수 (기본 3개)
    """

    def check(
        self,
        state: DrawdownState,
        params: RiskParams,
        active_position_count: int,
    ) -> RiskCheckResult:
        """전체 리스크 검증 수행.

        Args:
            state: DrawdownManager에서 조회한 현재 드로다운 상태.
            params: AiTradingConfig에서 추출한 리스크 파라미터.
            active_position_count: 현재 열린 포지션 수.

        Returns:
            RiskCheckResult: allowed=True면 거래 가능, False면 차단 + reason.
        """
```

**검증 로직:**

```python
# 1. 쿨다운 확인
if state["is_suspended"] and state["cooldown_until"]:
    if datetime.fromisoformat(state["cooldown_until"]) > datetime.now(UTC):
        return RiskCheckResult(allowed=False, reason="쿨다운 활성", ...)

# 2. 일일 손실 한도
if state["daily_loss_ratio"] >= params["daily_max_loss_ratio"]:
    return RiskCheckResult(allowed=False, reason="일일 손실 한도 초과", ...)

# 3. MDD 한도
if state["mdd_ratio"] >= params["mdd_limit_ratio"]:
    return RiskCheckResult(allowed=False, reason="MDD 한도 초과", ...)

# 4. 동시 포지션 수
if active_position_count >= params["max_active_positions"]:
    return RiskCheckResult(allowed=False, reason="최대 포지션 도달", ...)

return RiskCheckResult(allowed=True, reason="OK", ...)
```

### 6.2 FixedFractionalSizer + HalfKellySizer (position_sizing.py) — 순수 계산

ABC 미사용 — 두 독립 클래스의 `@staticmethod.calculate()` 시그니처가 동일하므로 불필요한 추상화 제거. 현재 사용처가 engine.py 1곳뿐.

```python
"""포지션 사이징 — Fixed Fractional + Half-Kelly.

순수 계산 모듈 — 외부 의존성 없음.
두 개의 독립 클래스 — engine.py에서 둘 다 실행 후 보수적(작은) 결과 선택.
"""
from __future__ import annotations

from decimal import Decimal

from app.trading.strategy.types import TradingSignal

from .constants import KELLY_HALF_FACTOR, SIGNAL_MULTIPLIER
from .types import PositionSizeResult, RiskParams


class FixedFractionalSizer:
    """Fixed Fractional: 투자금 = (총자산 × 리스크비율) / 손절비율.

    1. risk_amount = total_capital × stop_loss_ratio
    2. stop_loss_pct = |entry_price - stop_loss_price| / entry_price
    3. investment = risk_amount / stop_loss_pct
    4. × SignalStrength 배수 × position_scale
    5. min(investment, total_capital × max_investment_ratio)
    """

    @staticmethod
    def calculate(
        total_capital: Decimal,
        available_balance: Decimal,
        signal: TradingSignal,
        params: RiskParams,
    ) -> PositionSizeResult: ...


class HalfKellySizer:
    """Half-Kelly: Kelly% = W - (1-W)/R → Half-Kelly = Kelly × 0.5.

    1. kelly_pct = win_rate - (1 - win_rate) / avg_rr_ratio
    2. half_kelly_pct = max(kelly_pct × 0.5, 0)  # 음수 방지
    3. investment = total_capital × half_kelly_pct
    4. × SignalStrength 배수 × position_scale
    5. min(investment, total_capital × max_investment_ratio)
    """

    @staticmethod
    def calculate(
        total_capital: Decimal,
        available_balance: Decimal,
        signal: TradingSignal,
        params: RiskParams,
    ) -> PositionSizeResult: ...
```

**engine.py에서 두 sizer 모두 실행 + min 선택:**

```python
# engine.py 내부
ff_result = FixedFractionalSizer.calculate(capital, balance, signal, params)
hk_result = HalfKellySizer.calculate(capital, balance, signal, params)

# PRD §7.5.1: 보수적 선택
if ff_result["investment_amount"] <= hk_result["investment_amount"]:
    position_size = ff_result
else:
    position_size = hk_result

# available_balance 초과 검사
if position_size["investment_amount"] > available_balance:
    raise PositionSizingError("잔고 부족")
```

### 6.3 DynamicStopLoss (sl_tp.py) — 순수 계산

```python
"""동적 손절/익절 + Trailing Stop 계산.

순수 계산 모듈 — 외부 의존성 없음.
v1-17 ExitParams 기반으로 StopLossParams + TrailingStopState 생성.
"""
from __future__ import annotations

from .constants import TRAILING_STOP_ATR_MULT, TRAILING_TRIGGER_RATIO
from .types import StopLossParams, TrailingStopState


class DynamicStopLoss:
    """동적 손절/익절 + Trailing Stop 계산."""

    @staticmethod
    def calculate(
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        atr: float,
        stop_loss_atr_mult: float,
        take_profit_atr_mult: float,
    ) -> StopLossParams:
        """최종 SL/TP + Trailing Stop 파라미터 계산.

        Trailing Stop 활성화 기준:
        - 가격이 익절 50% 지점 도달 시 활성화
        - 활성화 후 ATR × 1.0 거리로 추적
        """

    @staticmethod
    def init_trailing_state(
        entry_price: float,
        stop_loss_params: StopLossParams,
    ) -> TrailingStopState:
        """체결 후 TrailingStopState 초기화."""

    @staticmethod
    def update_trailing_stop(
        state: TrailingStopState,
        current_price: float,
        atr: float,
    ) -> TrailingStopState:
        """Trailing Stop 상태 업데이트 (가격 모니터링 시 호출).

        1. 가격이 activation_threshold 도달 → is_active=True
        2. is_active 상태에서 peak_price 갱신
        3. current_stop = peak_price - ATR × 1.0
        """

    @staticmethod
    def should_exit(
        state: TrailingStopState,
        current_price: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> tuple[bool, str]:
        """청산 여부 판단.

        Returns:
            (should_exit, reason): "stop_loss" | "take_profit" | "trailing_stop"
        """
```

### 6.4 DrawdownManager (drawdown_manager.py) — Redis 의존

```python
"""드로다운 관리 — Redis Hash 기반 상태 저장/조회.

단일 Hash 키: trading:drawdown:{user_id}:{exchange_account_id}
TTL: 48시간 (갱신 시 리셋)
"""
from __future__ import annotations

import logging
from decimal import Decimal

from redis.asyncio import Redis

from .constants import COOLDOWN_SECONDS, DRAWDOWN_HASH_TTL
from .types import DrawdownState

logger = logging.getLogger(__name__)


class DrawdownManager:
    """드로다운 상태 관리 (Redis Hash).

    Redis 키 패턴:
    - trading:drawdown:{user_id}:{exchange_account_id}  (Hash, TTL=48h)
      fields: daily_loss_ratio, mdd_ratio, consecutive_losses,
              is_suspended, cooldown_until, peak_balance

    - trading:positions:{user_id}:{exchange_account_id}  (Set of order_ids, TTL=24h)
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get_state(
        self,
        user_id: str,
        exchange_account_id: str,
    ) -> DrawdownState:
        """현재 드로다운 상태 조회 (Redis HGETALL).

        키 미존재 시 기본값(0/false) 반환.
        """

    async def record_trade_result(
        self,
        user_id: str,
        exchange_account_id: str,
        pnl_ratio: float,
        current_balance: Decimal,
    ) -> DrawdownState:
        """거래 결과 기록 + 드로다운 상태 업데이트.

        수익: consecutive_losses 리셋.
        손실: daily_loss_ratio += |pnl_ratio|, consecutive_losses += 1, MDD 갱신.
        연속 3회 손실: cooldown_until 설정 + is_suspended=True.
        """

    async def get_active_position_count(
        self,
        user_id: str,
        exchange_account_id: str,
    ) -> int:
        """열린 포지션 수 조회 (Redis Set SCARD)."""

    async def add_position(
        self,
        user_id: str,
        exchange_account_id: str,
        order_id: str,
    ) -> None:
        """열린 포지션 추가 (Redis SADD)."""

    async def remove_position(
        self,
        user_id: str,
        exchange_account_id: str,
        order_id: str,
    ) -> None:
        """포지션 제거 (Redis SREM, 체결/취소 시)."""

    async def reset_daily(
        self,
        user_id: str,
        exchange_account_id: str,
    ) -> None:
        """일일 손실 리셋 (KST 00:00, 스케줄러/Celery에서 호출)."""

    async def set_suspension(
        self,
        user_id: str,
        exchange_account_id: str,
        reason: str,
        cooldown_seconds: int = COOLDOWN_SECONDS,
    ) -> None:
        """자동 중지 + 쿨다운 설정."""
```

**Redis 키 패턴:**

```
# Hash — 드로다운 상태
trading:drawdown:{user_id}:{exchange_account_id}
  daily_loss_ratio    (float)
  mdd_ratio           (float)
  consecutive_losses  (int)
  is_suspended        ("0" | "1")
  cooldown_until      (ISO datetime str | "")
  peak_balance        (float)
  TTL = 48h

# Set — 열린 포지션 ID
trading:positions:{user_id}:{exchange_account_id}
  members: order_id (str, UUID)
  TTL = 24h
```

> 기존 프로젝트 패턴(`auth:`, `rate:`, `trading:` 접두사)과 일관성 유지. redis_keys.py에 키 생성 헬퍼 추가.

### 6.5 OrderTracker (order_tracker.py) — PG + Provider 의존

PENDING → place_order → 상태 전이 로직을 자체 구현. OrderService를 import하지 않음 (의존 방향 유지).

`OrderRepository` 직접 주입 — `repositories/`는 인프라 레이어이므로 `trading/ → repositories/` 의존 허용 (`services/`도 `repositories/`에 의존).

```python
"""주문 생성/상태 추적 — OrderRepository + 거래소 폴링.

ExchangeRestProvider + OrderRepository 의존.
OrderService를 import하지 않음 (의존 방향: api → services → trading/).
OrderRepository.create(is_ai_order=True) 직접 호출 — 별도 update_ai_flag() 불필요.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from uuid import UUID, uuid4

from app.repositories.order_repository import OrderRepository
from app.providers.base import ExchangeRestProvider
from app.providers.types import Order, OrderResult
from app.providers.enums import OrderMethod, OrderSide, OrderStatus

from .constants import PARTIAL_FILL_POLL_INTERVAL, PARTIAL_FILL_WAIT_SECONDS

logger = logging.getLogger(__name__)


class OrderTracker:
    """주문 생성 + 부분 체결 추적.

    1. OrderRepository.create(is_ai_order=True)로 TradeOrder INSERT (status=pending)
    2. Provider.place_order() 호출
    3. 결과 반영 (status, exchange_order_id, executed_* 필드)
    4. 부분 체결 시 60초 대기 + 10초 폴링
    5. TradeOrderEvent 이력 기록
    """

    def __init__(self, order_repo: OrderRepository) -> None:
        self._order_repo = order_repo

    async def create_order(
        self,
        provider: ExchangeRestProvider,
        *,
        user_id: UUID,
        exchange_account_id: UUID,
        coin_id: UUID,
        market: str,
        side: OrderSide,
        method: OrderMethod,
        quantity: Decimal,
        amount: Decimal | None,
        price: Decimal | None,
    ) -> tuple[TradeOrder, OrderResult]:
        """주문 생성 + 거래소 전송 + DB 저장.

        1. self._order_repo.create(is_ai_order=True) → PENDING INSERT
        2. Provider.place_order()
        3. 결과 반영 (status, exchange_order_id, executed_* 필드)
        4. TradeOrderEvent 기록
        5. 실패 시 status=failed + 예외 raise

        Note:
            is_ai_order=True 고정 — OrderRepository.create() 시 직접 설정.
            별도 update_ai_flag() 불필요.

        Returns:
            (TradeOrder, OrderResult): DB 레코드 + 거래소 응답.

        Raises:
            OrderExecutionError: 거래소 주문 실패.
        """

    async def wait_for_fill(
        self,
        provider: ExchangeRestProvider,
        trade_order: TradeOrder,
    ) -> TradeOrder:
        """부분 체결 대기 + 폴링 + 잔량 처리.

        1. 60초 대기 (PARTIAL_FILL_WAIT_SECONDS)
        2. 10초 간격 provider.get_order() 폴링
        3. filled → 즉시 반환
        4. 60초 초과 시 provider.cancel_order()로 잔량 취소
        5. 체결된 수량 보존, DB 업데이트

        Returns:
            갱신된 TradeOrder.
        """

    @staticmethod
    async def _cancel_remaining(
        provider: ExchangeRestProvider,
        market: str,
        exchange_order_id: str,
    ) -> bool:
        """미체결 잔량 취소."""
```

### 6.6 TradeLogger (trade_logger.py) — Beanie Document 직접 사용

생성자 없음 — `TradeLog`는 Beanie Document이므로 `AsyncIOMotorDatabase` 주입 불필요. `doc.insert()` / `doc.save()` 직접 호출.

```python
"""거래 로그 기록 — MongoDB trade_logs.

기존 TradeLog Document(documents/trading_logs.py) 재사용.
Beanie Document CRUD — DB 주입 불필요 (Beanie가 내부 관리).
"""
from __future__ import annotations

import logging
from datetime import datetime, UTC
from decimal import Decimal
from uuid import UUID

from beanie import PydanticObjectId

from app.documents.trading_logs import TradeLog
from app.trading.strategy.types import TradingSignal

from .types import PositionSizeResult

logger = logging.getLogger(__name__)


class TradeLogger:
    """MongoDB 거래 로그 기록.

    Beanie Document 직접 사용 — 생성자/DB 주입 없음.
    TradeLog(...).insert() 방식.
    """

    async def log_entry(
        self,
        trade_order_id: UUID,
        signal: TradingSignal,
        position_size: PositionSizeResult,
        *,
        user_id: UUID,
        coin_symbol: str,
        market_code: str,
        exchange_type: str,
        order_type: str,
        entry_price: Decimal,
        quantity: Decimal,
        fee: Decimal,
        ai_decision_id: PydanticObjectId | None = None,
    ) -> PydanticObjectId:
        """진입 거래 로그 기록.

        Returns:
            MongoDB document ID.
        """

    async def update_on_close(
        self,
        trade_log_id: PydanticObjectId,
        exit_price: Decimal,
        pnl_amount: Decimal,
        pnl_ratio: Decimal,
        holding_minutes: int,
    ) -> None:
        """청산 시 로그 업데이트 (status: open → closed)."""
```

### 6.7 ExecutionEngine (engine.py) — 오케스트레이터

```python
"""주문 실행 엔진 — 오케스트레이터.

TradingSignal → 리스크 검증 → 포지션 사이징 → 주문 실행 → 상태 추적 → 로깅.
OrderService를 import하지 않음 — Provider + AsyncSession 직접 주입.
"""
from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.providers.base import ExchangeRestProvider
from app.trading.strategy.types import TradingSignal

from .constants import MAX_RETRY_COUNT, RETRY_INTERVAL_SECONDS
from .drawdown_manager import DrawdownManager
from .exceptions import OrderExecutionError, PositionSizingError, RiskLimitExceeded
from .order_tracker import OrderTracker
from .position_sizing import FixedFractionalSizer, HalfKellySizer
from .risk_manager import RiskManager
from .sl_tp import DynamicStopLoss
from .trade_logger import TradeLogger
from .types import ExecutionResult, TradeExecutionContext

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """주문 실행 오케스트레이터.

    의존성 주입 (Celery task에서 직접 인스턴스화):
    - risk_manager: RiskManager (순수 계산)
    - drawdown_manager: DrawdownManager (Redis)
    - order_tracker: OrderTracker (OrderRepository)
    - trade_logger: TradeLogger (Beanie, 주입 없음)
    - provider: ExchangeRestProvider (거래소)

    Note:
      FixedFractionalSizer, HalfKellySizer는 @staticmethod이므로 주입 불필요.
      DynamicStopLoss도 @staticmethod이므로 주입 불필요.
    """

    def __init__(
        self,
        risk_manager: RiskManager,
        drawdown_manager: DrawdownManager,
        order_tracker: OrderTracker,
        trade_logger: TradeLogger,
        provider: ExchangeRestProvider,
    ) -> None:
        self._risk_manager = risk_manager
        self._drawdown = drawdown_manager
        self._tracker = order_tracker
        self._logger = trade_logger
        self._provider = provider

    async def execute(
        self,
        context: TradeExecutionContext,
    ) -> ExecutionResult:
        """TradingSignal → 주문 실행 전체 흐름.

        1. DrawdownManager.get_state() → 드로다운 상태 조회 (Redis)
        2. RiskManager.check() → 리스크 사전 검증 (순수)
        3. FixedFractionalSizer + HalfKellySizer → min 보수적 선택 (순수)
        4. DynamicStopLoss.calculate() → SL/TP 확정 (순수)
        5. OrderTracker.create_order() → 주문 생성 (PG + Provider)
        6. [partial 시] OrderTracker.wait_for_fill() → 부분 체결 대기
        7. DrawdownManager.add_position() → 열린 포지션 추가
        8. TradeLogger.log_entry() → MongoDB 기록
        9. 재시도: 30초 간격 최대 2회 (네트워크/가용성 오류만)
        """
```

**재시도 로직:**

```python
_RETRYABLE_EXCEPTIONS = (
    ExchangeNetworkError,
    ExchangeUnavailableError,
)

async def _execute_with_retry(self, context, position_size, sl_params):
    for attempt in range(MAX_RETRY_COUNT + 1):
        try:
            return await self._place_and_track(context, position_size, sl_params)
        except _RETRYABLE_EXCEPTIONS as exc:
            if attempt < MAX_RETRY_COUNT:
                logger.warning("retry %d/%d: %s", attempt + 1, MAX_RETRY_COUNT, exc)
                await asyncio.sleep(RETRY_INTERVAL_SECONDS)
            else:
                raise OrderExecutionError("재시도 초과", exchange_error=exc)
    # InsufficientBalance, AuthError, PermissionError → 즉시 실패 (catch 안 함)
```

---

## 7. 기존 타입과의 연결

| 기존 타입 | 위치 | 연결 방식 |
|----------|------|---------|
| `TradingSignal` | strategy/types.py | `TradeExecutionContext.signal` 그대로 사용 |
| `ExitParams` | strategy/types.py | `DynamicStopLoss.calculate()` 입력 → StopLossParams 생성 |
| `SignalStrength` | strategy/types.py | `SIGNAL_MULTIPLIER` 배수 매핑 |
| `OrderResult` | providers/types.py | `OrderTracker.create_order()` 반환 |
| `ExchangeRestProvider` | providers/base.py | `ExecutionEngine` + `OrderTracker`에 ABC로 주입 |
| `TradeOrder` | models/trading.py | `OrderTracker`에서 생성/업데이트 |
| `TradeLog` | documents/trading_logs.py | `TradeLogger`에서 생성/업데이트 |
| `AiTradingConfig` | models/trading.py | 서비스 레이어에서 `RiskParams`로 변환 후 주입 |

---

## 8. Decimal 사용 규칙

기존 TradeOrder, providers/types.py 패턴과 동일:

| 분류 | 타입 | 예시 |
|------|------|------|
| 금액 | `Decimal` | quantity, investment_amount, total_capital, available_balance, fee |
| 비율/배수 | `float` | risk_ratio, kelly_fraction, daily_loss_ratio, mdd_ratio, strength_multiplier |
| 가격 | `float` (순수 계산) / `Decimal` (DB 저장) | entry_price, stop_loss_price (types.py: float, TradeOrder: Decimal) |

---

## 9. DI (의존성 주입) 설계 — Celery Task

v1-18의 ExecutionEngine은 **FastAPI DI를 사용하지 않음**. Celery task에서 직접 인스턴스화.

```python
# tasks/ai_trading.py (향후 구현)
@celery_app.task
async def execute_ai_trading(
    user_id: str,
    exchange_account_id: str,
    signal_data: dict,
    risk_params_data: dict,
):
    from app.core.database import async_session_factory
    from app.core.redis import get_redis_client
    from app.providers.factory import ExchangeProviderFactory
    from app.repositories.order_repository import OrderRepository

    redis = await get_redis_client()
    provider = ExchangeProviderFactory.instance().create(
        exchange_type, api_key, api_secret, user_id
    )
    await provider.initialize()

    async with async_session_factory() as session:
        order_repo = OrderRepository(session)

        engine = ExecutionEngine(
            risk_manager=RiskManager(),
            drawdown_manager=DrawdownManager(redis),
            order_tracker=OrderTracker(order_repo),
            trade_logger=TradeLogger(),
            provider=provider,
        )

        context = TradeExecutionContext(
            user_id=user_id,
            exchange_account_id=exchange_account_id,
            signal=signal_data,
            risk_params=risk_params_data,
            ...
        )
        result = await engine.execute(context)

    await provider.close()
```

**의존성 트리:**

```
ExecutionEngine
├── RiskManager (순수 계산, 상태 없음)
├── FixedFractionalSizer (@staticmethod, 주입 불필요)
├── HalfKellySizer (@staticmethod, 주입 불필요)
├── DynamicStopLoss (@staticmethod, 주입 불필요)
├── DrawdownManager ← Redis
├── OrderTracker ← OrderRepository (PG session 내장)
├── TradeLogger ← Beanie Document 직접 (주입 없음)
└── ExchangeRestProvider (Factory에서 생성)
```

> **api/deps.py 변경 없음** — ExecutionEngine은 서비스 레이어(services/)에서 사용하지 않고 Celery task에서 직접 생성.

**OrderRepository 확장 (신규 메서드 1개):**

```python
# repositories/order_repository.py에 추가
async def count_active_ai_orders(self, user_id: uuid.UUID) -> int:
    """사용자의 미체결 AI 주문 수 (전 계정 합산).

    RiskManager.check()에서 최대 포지션 수 검증용.
    WHERE is_ai_order=True AND status IN ('open', 'partial')
    인덱스: ix_trade_orders_active (PARTIAL) 활용.
    """
    result = await self._db.execute(
        select(func.count())
        .select_from(TradeOrder)
        .where(
            TradeOrder.user_id == user_id,
            TradeOrder.is_ai_order.is_(True),
            TradeOrder.status.in_(["open", "partial"]),
        )
    )
    return result.scalar_one()
```

---

## 10. 데이터 흐름 시퀀스 다이어그램

### 10.1 주문 실행 전체 흐름

```
Celery Task          ExecutionEngine      DrawdownMgr      RiskManager     PositionSizer     OrderTracker      TradeLogger
    │                      │                   │                │                │                │                │
    │  context             │                   │                │                │                │                │
    │ ──────────────────► │                   │                │                │                │                │
    │                      │                   │                │                │                │                │
    │                      │  get_state()      │                │                │                │                │
    │                      │ ────────────────► │                │                │                │                │
    │                      │                   │ Redis HGETALL  │                │                │                │
    │                      │ ◄──────────────── │                │                │                │                │
    │                      │  DrawdownState    │                │                │                │                │
    │                      │                   │                │                │                │                │
    │                      │  check(state,     │                │                │                │                │
    │                      │    params, count) │                │                │                │                │
    │                      │ ──────────────────────────────────►│                │                │                │
    │                      │ ◄──────────────────────────────────│                │                │                │
    │                      │  RiskCheckResult  │                │                │                │                │
    │                      │  (allowed=true)   │                │                │                │                │
    │                      │                   │                │                │                │                │
    │                      │  calculate() ×2   │                │                │                │                │
    │                      │ ──────────────────────────────────────────────────►│                │                │
    │                      │ ◄──────────────────────────────────────────────────│                │                │
    │                      │  min(FF, HK)      │                │                │                │                │
    │                      │                   │                │                │                │                │
    │                      │  create_order()   │                │                │                │                │
    │                      │ ──────────────────────────────────────────────────────────────────►│                │
    │                      │                   │                │                │                │  PG INSERT     │
    │                      │                   │                │                │                │  + place_order │
    │                      │ ◄──────────────────────────────────────────────────────────────────│                │
    │                      │  (TradeOrder,     │                │                │                │                │
    │                      │   OrderResult)    │                │                │                │                │
    │                      │                   │                │                │                │                │
    │                      │  add_position()   │                │                │                │                │
    │                      │ ────────────────► │                │                │                │                │
    │                      │                   │  Redis SADD    │                │                │                │
    │                      │                   │                │                │                │                │
    │                      │  log_entry()      │                │                │                │                │
    │                      │ ──────────────────────────────────────────────────────────────────────────────────►│
    │                      │                   │                │                │                │                │ MongoDB
    │                      │                   │                │                │                │                │
    │ ◄────────────────── │                   │                │                │                │                │
    │  ExecutionResult     │                   │                │                │                │                │
```

### 10.2 리스크 차단 흐름

```
ExecutionEngine      DrawdownMgr      RiskManager
    │                    │                │
    │  get_state()       │                │
    │ ──────────────────►│                │
    │ ◄──────────────────│                │
    │  daily_loss=0.063  │                │
    │                    │                │
    │  check(state, params, count)        │
    │ ──────────────────────────────────► │
    │                    │                │
    │                    │  0.063 >= 0.05 │
    │                    │  → allowed=false│
    │ ◄──────────────────────────────────│
    │  reason="일일 손실 한도 초과"       │
    │                    │                │
    │  → ExecutionResult(               │
    │      status="skipped",             │
    │      skipped_reason="일일 손실...")  │
```

### 10.3 부분 체결 + 잔량 처리 흐름

```
ExecutionEngine      OrderTracker        Provider
    │                    │                   │
    │  create_order()    │                   │
    │ ──────────────────►│                   │
    │                    │  place_order()    │
    │                    │ ────────────────► │
    │                    │ ◄──────────────── │
    │                    │  status=partial   │
    │                    │                   │
    │  wait_for_fill()   │                   │
    │ ──────────────────►│                   │
    │                    │  get_order() t=0  │
    │                    │ ────────────────► │
    │                    │ ◄──────────────── │
    │                    │  partial          │
    │                    │                   │
    │                    │  sleep(10s)       │
    │                    │  get_order() t=10 │
    │                    │ ────────────────► │
    │                    │ ◄──────────────── │
    │                    │  partial          │
    │                    │                   │
    │                    │  ... (6회) ...    │
    │                    │                   │
    │                    │  t=60, 여전히     │
    │                    │  cancel_order()   │
    │                    │ ────────────────► │
    │                    │ ◄──────────────── │
    │                    │  cancelled        │
    │                    │                   │
    │                    │  PG 업데이트      │
    │                    │  (체결분 보존)    │
    │ ◄──────────────────│                   │
    │  TradeOrder        │                   │
```

---

## 11. Redis 키 패턴 (redis_keys.py 확장)

```python
# ── Trading / Risk Management ────────────────────────────────────────────

@staticmethod
def drawdown(user_id: str, exchange_account_id: str) -> str:
    """드로다운 상태 Hash."""
    return f"trading:drawdown:{user_id}:{exchange_account_id}"

@staticmethod
def positions(user_id: str, exchange_account_id: str) -> str:
    """열린 포지션 Set."""
    return f"trading:positions:{user_id}:{exchange_account_id}"
```

```python
# RedisTTL 추가
DRAWDOWN = 48 * 3600     # 48시간 (드로다운 Hash)
POSITIONS = 24 * 3600    # 24시간 (열린 포지션 Set)
```

---

## 12. 구현 파일 및 예상 코드량

| 파일 | 핵심 함수/클래스 | 예상 라인 |
|------|----------------|----------|
| `types.py` | 9개 TypedDict | ~120 |
| `constants.py` | 리스크 상수 20+ | ~60 |
| `exceptions.py` | 4개 예외 클래스 | ~40 |
| `risk_manager.py` | RiskManager.check() (순수) | ~70 |
| `position_sizing.py` | FixedFractionalSizer + HalfKellySizer (@staticmethod) | ~130 |
| `sl_tp.py` | DynamicStopLoss (4 메서드) | ~110 |
| `drawdown_manager.py` | DrawdownManager (7 메서드) | ~150 |
| `order_tracker.py` | OrderTracker (3 메서드) | ~150 |
| `trade_logger.py` | TradeLogger (2 메서드) | ~80 |
| `engine.py` | ExecutionEngine (execute, _execute_with_retry) | ~200 |
| `__init__.py` | public exports | ~30 |
| **합계** | | **~1,140** |

**기존 파일 수정:**

| 파일 | 변경 내용 | 예상 라인 추가 |
|------|----------|-------------|
| `core/redis_keys.py` | drawdown/positions 키 + TTL 추가 | ~15 |
| `repositories/order_repository.py` | `count_active_ai_orders()` 메서드 추가 | ~15 |

---

## 13. 테스트 전략

### 13.1 단위 테스트 (~45건)

| 대상 | 테스트 내용 | 건수 |
|------|-----------|------|
| `risk_manager.py` | 쿨다운 차단, 일일 손실 차단, MDD 차단, 포지션 초과, 전체 통과, 경계값 | 8 |
| `position_sizing.py` | FF 기본, HK 기본, 음수 Kelly(=0), 캡, 강도 배수, position_scale, 잔고 부족, FF vs HK 비교 | 10 |
| `sl_tp.py` | SL/TP 계산 (buy/sell), Trailing 초기화, 활성화, 추적 업데이트, 청산 판단 3종 | 8 |
| `drawdown_manager.py` | 손실 기록, 수익 리셋, 쿨다운 설정, MDD 갱신, 일일 리셋, 포지션 추가/제거, Redis mock | 8 |
| `order_tracker.py` | 완전 체결, 부분→대기→체결, 부분→타임아웃→취소, 실패 | 5 |
| `trade_logger.py` | 진입 로그, 청산 업데이트, 필드 매핑 | 3 |
| `engine.py` | 정상 실행, 리스크 차단, 재시도 성공, 재시도 초과 | 3 |

### 13.2 통합 테스트 (~5건)

| 시나리오 | 설명 |
|---------|------|
| 풀 파이프라인 | TradingSignal → 리스크 통과 → 사이징 → 주문 실행 → 로그 |
| 리스크 차단 | 일일 손실 5% 초과 → ExecutionResult(status="skipped") |
| 연속 손실 쿨다운 | 3회 손실 기록 → 쿨다운 활성화 → 다음 execute() 차단 |
| 부분 체결 처리 | partial → 60초 대기 → 잔량 취소 → 체결분 보존 |
| MDD 일시정지 | MDD 15% 초과 → 전체 거래 일시정지 |

---

## 14. 설계 결정 요약 (ADR)

### ADR-18-1: Trailing Stop은 polling 방식 (v1-18)
- **결정**: `DynamicStopLoss.update_trailing_stop()` + `should_exit()`를 polling 방식으로 구현. WS 스트림 기반 실시간 모니터링은 v2.
- **근거**: WS 구독 기반 가격 모니터링 루프는 v1-18 범위 초과. Polling으로 기능 검증 후 최적화.

### ADR-18-2: OrderService 미사용 — OrderRepository 직접 주입 (code-architect 합의)
- **결정**: `trading/execution/engine.py`에서 `services/order_service.py`를 import하지 않음. OrderTracker에 `OrderRepository` 직접 주입. `OrderRepository.create(is_ai_order=True)` 직접 호출 — 별도 `update_ai_flag()` 불필요.
- **근거**: 의존 방향 규칙 `api → services → trading/` (단방향). `trading/ → repositories/`는 인프라 레이어 참조로 허용 (`services/`도 `repositories/`에 의존). OrderTracker가 PENDING → place_order → 상태 전이 로직을 자체 구현.

### ADR-18-3: RiskManager 순수 계산 (code-architect 합의)
- **결정**: `risk_manager.py`는 Redis/DB 의존 없는 순수 계산. DrawdownState + RiskParams 입력 → RiskCheckResult 출력.
- **근거**: 테스트 용이성 + SRP. Redis 상태 관리는 DrawdownManager 전담.

### ADR-18-4: 내부 예외는 exceptions.py 별도 파일 (code-architect 합의)
- **결정**: `trading/execution/exceptions.py`에 TradeExecutionError, RiskLimitExceeded, PositionSizingError, OrderExecutionError 배치. `core/exceptions.py`에 ExecutionErrors AppError 팩토리는 v1-18에서 추가하지 않음.
- **근거**: v1-18은 내부 엔진 (API 엔드포인트 없음). providers/exceptions.py ↔ ExchangeErrors 패턴과 동일한 이중 레이어. 향후 API 노출 시 추가.

### ADR-18-5: Redis Hash 방식으로 드로다운 상태 통합 (code-architect 합의)
- **결정**: 개별 키 6개 대신 단일 Hash `trading:drawdown:{user_id}:{exchange_account_id}` + TTL=48h.
- **근거**: HGETALL로 한 번에 조회. 기존 프로젝트 키 패턴(`auth:`, `trading:` 접두사)과 일관성.

### ADR-18-6: PositionSizer ABC 미사용 — 독립 클래스 + @staticmethod (code-architect 합의)
- **결정**: ABC 제거, FixedFractionalSizer + HalfKellySizer를 독립 클래스(`@staticmethod.calculate()`)로 구현. engine.py에서 **둘 다 실행 후 보수적(작은) 결과 선택**.
- **근거**: PRD §7.5.1 "보수적 선택". 현재 사용처가 engine.py 1곳뿐이므로 ABC는 불필요한 추상화. 두 클래스의 메서드 시그니처가 동일하므로 ABC 없이도 일관성 유지.

### ADR-18-7: 주문 재시도 전략
- **결정**: 네트워크/가용성 오류만 30초 간격 최대 2회 재시도. 사용자 오류(잔고, 인증)는 즉시 실패.
- **근거**: PRD §7.8. 이중 주문 방지.

### ADR-18-8: Decimal 사용 규칙 (code-architect 합의)
- **결정**: 금액=Decimal (quantity, investment_amount, total_capital 등), 비율/배수=float (risk_ratio, kelly_fraction 등).
- **근거**: 기존 TradeOrder, providers/types.py 패턴과 동일.

### ADR-18-9: DI는 Celery task 직접 인스턴스화 (code-architect 합의)
- **결정**: FastAPI DI (deps.py) 미사용. Celery task에서 ExecutionEngine을 직접 생성.
- **근거**: ExecutionEngine은 백그라운드 자동매매 로직 — HTTP 요청 컨텍스트가 아닌 Celery task에서 실행.

### ADR-18-10: HalfKelly W/R 초기값 (code-architect 합의)
- **결정**: RiskParams에 `win_rate_estimate: float = 0.5`, `avg_rr_ratio: float = 1.5` 추가. 히스토리 없는 첫 실행 시 기본값 사용.
- **근거**: 히스토리 기반 동적 조정은 v2. 현재는 보수적 초기값으로 시작.

---

## 15. 의존성

### 기존 패키지 (신규 추가 없음)
- `trading/strategy/types.py`: TradingSignal, ExitParams, SignalStrength, StrategyName
- `providers/base.py`: ExchangeRestProvider.place_order(), get_order(), cancel_order()
- `providers/types.py`: Order, OrderResult, Balance
- `providers/enums.py`: OrderSide, OrderMethod, OrderStatus
- `models/trading.py`: TradeOrder
- `models/trade_order_event.py`: TradeOrderEvent
- `documents/trading_logs.py`: TradeLog Document
- `core/redis_keys.py`: RedisKey, RedisTTL

### 신규 외부 라이브러리: 없음

---

## 16. 서브태스크 → 파일 매핑

| ST | 서브태스크 | 주요 파일 |
|----|----------|---------|
| ST1 | RiskManager | `types.py`, `constants.py`, `exceptions.py`, `risk_manager.py` |
| ST2 | Fixed Fractional 포지션 사이징 | `position_sizing.py` (FixedFractionalSizer) |
| ST3 | Half-Kelly 포지션 사이징 | `position_sizing.py` (HalfKellySizer 추가) |
| ST4 | ATR 동적 SL/TP | `sl_tp.py` |
| ST5 | 드로다운 관리 및 자동 중지 | `drawdown_manager.py`, `core/redis_keys.py` |
| ST6 | ExecutionEngine 기본 구조 | `engine.py`, `__init__.py` |
| ST7 | 포지션 사이징 적용 + 주문 생성 | `engine.py` (ST6 확장) |
| ST8 | 주문 상태 추적 | `order_tracker.py` |
| ST9 | MongoDB trade_logs 로깅 | `trade_logger.py` |
| ST10 | 통합/E2E 테스트 | `tests/` |

### 구현 순서 (의존성 기반)

```
Phase 1 (병렬): ST1(types+constants+exceptions+RiskManager)
              + ST2/ST3(PositionSizer ABC + FF + HK)
              + ST4(DynamicStopLoss)
Phase 2 (병렬): ST5(DrawdownManager) + ST8(OrderTracker) + ST9(TradeLogger)
Phase 3 (순차): ST6(Engine 기본) → ST7(Engine 사이징+주문)
Phase 4:        ST10(통합 테스트)
```
