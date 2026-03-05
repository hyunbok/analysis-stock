import uuid
from datetime import datetime

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class AiTradingConfig(Base):
    __tablename__ = "ai_trading_configs"
    __table_args__ = (
        Index("ix_ai_trading_configs_watchlist_coin_id", "watchlist_coin_id", unique=True),
        Index("ix_ai_trading_configs_is_enabled", "is_enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    watchlist_coin_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("watchlist_coins.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    max_investment_ratio: Mapped[float] = mapped_column(
        Numeric(5, 4), default=0.10, server_default=text("0.10")
    )
    stop_loss_ratio: Mapped[float] = mapped_column(
        Numeric(5, 4), default=0.02, server_default=text("0.02")
    )
    take_profit_ratio: Mapped[float] = mapped_column(
        Numeric(5, 4), default=0.03, server_default=text("0.03")
    )
    daily_max_loss_ratio: Mapped[float] = mapped_column(
        Numeric(5, 4), default=0.05, server_default=text("0.05")
    )
    primary_timeframe: Mapped[str] = mapped_column(
        String(10), default="5m", server_default="5m"
    )
    confirmation_timeframes: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=lambda: ["15m", "1h"], server_default=text("ARRAY['15m','1h']")
    )
    strategy_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disable_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    watchlist_coin: Mapped["WatchlistCoin"] = relationship(
        "WatchlistCoin", back_populates="ai_trading_config"
    )
    history: Mapped[list["AiTradingConfigHistory"]] = relationship(
        "AiTradingConfigHistory", back_populates="config", cascade="all, delete-orphan"
    )


class AiTradingConfigHistory(Base):
    __tablename__ = "ai_trading_config_histories"
    __table_args__ = (
        Index("ix_ai_trading_config_histories_config_id", "config_id"),
        Index("ix_ai_trading_config_histories_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    config_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("ai_trading_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(10), nullable=False)
    change_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    config: Mapped["AiTradingConfig"] = relationship(
        "AiTradingConfig", back_populates="history"
    )


class TradeOrder(Base):
    __tablename__ = "trade_orders"
    __table_args__ = (
        Index("ix_trade_orders_user_id", "user_id"),
        Index("ix_trade_orders_status", "status"),
        Index("ix_trade_orders_created_at", "created_at"),
        Index("ix_trade_orders_is_ai_order", "is_ai_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("user_exchange_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    coin_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("coins.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_type: Mapped[str] = mapped_column(String(10), nullable=False)
    order_method: Mapped[str] = mapped_column(String(10), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    executed_quantity: Mapped[float] = mapped_column(
        Numeric(20, 8), default=0, server_default=text("0")
    )
    fee: Mapped[float] = mapped_column(
        Numeric(20, 8), default=0, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_ai_order: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    exchange_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="trade_orders")
    coin: Mapped["Coin"] = relationship("Coin", back_populates="trade_orders")
    exchange_account: Mapped["UserExchangeAccount"] = relationship(
        "UserExchangeAccount", back_populates="trade_orders"
    )


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    __table_args__ = (
        Index("ix_price_alerts_user_id", "user_id"),
        Index("ix_price_alerts_is_active", "is_active"),
        Index("ix_price_alerts_coin_id", "coin_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    coin_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("coins.id", ondelete="CASCADE"),
        nullable=False,
    )
    exchange_account_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("user_exchange_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    condition: Mapped[str] = mapped_column(String(10), nullable=False)
    target_price: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    is_triggered: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="price_alerts")
    coin: Mapped["Coin"] = relationship("Coin", back_populates="price_alerts")
    exchange_account: Mapped["UserExchangeAccount | None"] = relationship(
        "UserExchangeAccount", back_populates="price_alerts"
    )
