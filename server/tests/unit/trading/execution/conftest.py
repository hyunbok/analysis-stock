"""execution 패키지 단위 테스트 공통 픽스처."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.trading.execution.types import (
    DrawdownState,
    RiskParams,
    StopLossParams,
    TradeExecutionContext,
    TrailingStopState,
)
from app.trading.strategy.types import ExitParams, TradingSignal


# ── RiskParams 헬퍼 ───────────────────────────────────────────────────────────

def make_risk_params(**overrides) -> RiskParams:
    defaults: RiskParams = {
        "max_investment_ratio": 0.10,
        "stop_loss_ratio": 0.02,
        "take_profit_ratio": 0.03,
        "daily_max_loss_ratio": 0.05,
        "max_active_positions": 3,
        "max_consecutive_losses": 3,
        "mdd_limit_ratio": 0.15,
        "win_rate_estimate": 0.5,
        "avg_rr_ratio": 1.5,
    }
    defaults.update(overrides)
    return defaults


# ── DrawdownState 헬퍼 ────────────────────────────────────────────────────────

def make_drawdown_state(**overrides) -> DrawdownState:
    defaults: DrawdownState = {
        "daily_loss_ratio": 0.0,
        "mdd_ratio": 0.0,
        "consecutive_losses": 0,
        "is_suspended": False,
        "cooldown_until": None,
        "peak_balance": 10_000_000.0,
        "detail": "테스트 상태",
    }
    defaults.update(overrides)
    return defaults


# ── TradingSignal 헬퍼 ────────────────────────────────────────────────────────

def make_exit_params(**overrides) -> ExitParams:
    defaults: ExitParams = {
        "stop_loss": 97_000_000.0,       # entry 100M → 3% 손절
        "take_profit": 104_500_000.0,    # 4.5% 익절
        "stop_loss_atr_mult": 1.5,
        "take_profit_atr_mult": 2.0,
        "risk_reward_ratio": 1.5,
    }
    defaults.update(overrides)
    return defaults


def make_trading_signal(**overrides) -> TradingSignal:
    defaults: TradingSignal = {
        "strategy_name": "trend_ma",
        "action": "buy",
        "confidence": 0.75,
        "entry_price": 100_000_000.0,   # BTC 1억원
        "exit_params": make_exit_params(),
        "strength": "strong",
        "position_scale": 1.0,
        "mtf_weight": 1.0,
        "conditions": [],
        "regime_type": "trend",
        "detail": "TrendMA 진입 신호",
    }
    defaults.update(overrides)
    return defaults


# ── TradeExecutionContext 헬퍼 ────────────────────────────────────────────────

def make_execution_context(**overrides) -> TradeExecutionContext:
    defaults: TradeExecutionContext = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "exchange_account_id": "00000000-0000-0000-0000-000000000002",
        "coin_id": "00000000-0000-0000-0000-000000000003",
        "market": "KRW-BTC",
        "symbol": "BTC/KRW",
        "signal": make_trading_signal(),
        "risk_params": make_risk_params(),
        "total_capital": Decimal("10_000_000"),    # 1000만원
        "available_balance": Decimal("10_000_000"),
    }
    defaults.update(overrides)
    return defaults


# ── 미래/과거 ISO datetime 헬퍼 ───────────────────────────────────────────────

def future_iso(seconds: int = 3600) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def past_iso(seconds: int = 3600) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
