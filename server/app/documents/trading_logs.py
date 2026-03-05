from __future__ import annotations

from datetime import date, datetime, UTC
from typing import Optional
from uuid import UUID

import pymongo
from beanie import Document, Indexed
from beanie import PydanticObjectId
from bson import Decimal128
from pydantic import BaseModel, ConfigDict, Field


class IndicatorsSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ema_20: Optional[Decimal128] = None
    ema_50: Optional[Decimal128] = None
    ema_200: Optional[Decimal128] = None
    vwap: Optional[Decimal128] = None
    vwap_upper: Optional[Decimal128] = None
    vwap_lower: Optional[Decimal128] = None
    rsi: Optional[Decimal128] = None
    macd: Optional[Decimal128] = None
    macd_signal: Optional[Decimal128] = None
    macd_histogram: Optional[Decimal128] = None
    bb_upper: Optional[Decimal128] = None
    bb_middle: Optional[Decimal128] = None
    bb_lower: Optional[Decimal128] = None
    bb_percent_b: Optional[Decimal128] = None
    adx: Optional[Decimal128] = None
    plus_di: Optional[Decimal128] = None
    minus_di: Optional[Decimal128] = None
    atr: Optional[Decimal128] = None
    stochastic_k: Optional[Decimal128] = None
    stochastic_d: Optional[Decimal128] = None
    obv: Optional[Decimal128] = None
    williams_r: Optional[Decimal128] = None
    cci: Optional[Decimal128] = None


class TradeLog(Document):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    trade_order_id: UUID
    # Denormalized snapshot fields
    coin_symbol: str
    market_code: str
    exchange_type: str
    order_type: str
    order_method: str
    # Trade details
    price: Decimal128
    quantity: Decimal128
    fee: Decimal128
    is_ai_order: bool
    # AI context
    market_regime: Optional[str] = None  # trend/range/transition
    strategy_name: Optional[str] = None
    ai_decision_id: Optional[PydanticObjectId] = None
    reasoning_summary: Optional[str] = Field(None, max_length=200)
    strategy_params_snapshot: Optional[dict] = None
    # PnL tracking
    entry_price: Decimal128
    pnl_amount: Optional[Decimal128] = None
    pnl_ratio: Optional[Decimal128] = None
    holding_minutes: Optional[int] = None
    status: str = "open"  # open/closed
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "trade_logs"
        indexes = [
            pymongo.IndexModel([("user_id", pymongo.ASCENDING)]),
            pymongo.IndexModel([("trade_order_id", pymongo.ASCENDING)]),
            pymongo.IndexModel([("status", pymongo.ASCENDING)]),
            pymongo.IndexModel([("created_at", pymongo.DESCENDING)]),
        ]


class AiDecision(Document):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    coin_symbol: str
    market_regime: str
    regime_confidence: dict  # e.g. {"trend": 0.7, "range": 0.2, "transition": 0.1}
    selected_strategy: str
    action: str  # buy/sell/hold
    action_confidence: Decimal128
    indicators_snapshot: Optional[IndicatorsSnapshot] = None
    # GPT metadata
    gpt_model: str
    gpt_prompt_tokens: int
    gpt_completion_tokens: int
    gpt_raw_response: Optional[str] = None
    gpt_parsed_result: Optional[dict] = None
    # Context
    news_context_summary: Optional[str] = None
    trade_log_id: Optional[PydanticObjectId] = None
    execution_skipped_reason: Optional[str] = None
    analysis_duration_ms: Optional[int] = None
    celery_task_id: Optional[str] = None
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "ai_decisions"
        indexes = [
            pymongo.IndexModel([("user_id", pymongo.ASCENDING)]),
            pymongo.IndexModel([("coin_symbol", pymongo.ASCENDING)]),
            pymongo.IndexModel([("created_at", pymongo.ASCENDING)]),
            # TTL: 180 days = 15552000 seconds
            pymongo.IndexModel(
                [("created_at", pymongo.ASCENDING)],
                expireAfterSeconds=15552000,
                name="ai_decisions_ttl",
            ),
        ]


class DailyPnlReport(Document):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    report_date: date
    # Totals
    total_pnl: Decimal128
    trade_count: int
    win_rate: Decimal128
    # AI trades
    ai_pnl: Decimal128
    ai_trade_count: int
    ai_win_count: int
    # Manual trades
    manual_pnl: Decimal128
    manual_trade_count: int
    # Breakdowns
    regime_stats: Optional[dict] = None
    strategy_stats: Optional[dict] = None
    # Cumulative
    cumulative_pnl: Decimal128
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "daily_pnl_reports"
        indexes = [
            pymongo.IndexModel(
                [("user_id", pymongo.ASCENDING), ("report_date", pymongo.ASCENDING)],
                unique=True,
                name="daily_pnl_user_date_unique",
            ),
        ]
