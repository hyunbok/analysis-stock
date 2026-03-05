import uuid
from datetime import datetime

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Coin(Base):
    __tablename__ = "coins"
    __table_args__ = (
        UniqueConstraint("exchange_type", "market_code", name="uq_coin_exchange_market"),
        Index("ix_coins_symbol", "symbol"),
        Index("ix_coins_exchange_type", "exchange_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    name_ko: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exchange_type: Mapped[str] = mapped_column(String(20), nullable=False)
    market_code: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        pg.BOOLEAN, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    watchlist_coins: Mapped[list["WatchlistCoin"]] = relationship(
        "WatchlistCoin", back_populates="coin"
    )
    trade_orders: Mapped[list["TradeOrder"]] = relationship(
        "TradeOrder", back_populates="coin"
    )
    price_alerts: Mapped[list["PriceAlert"]] = relationship(
        "PriceAlert", back_populates="coin"
    )


class WatchlistCoin(Base):
    __tablename__ = "watchlist_coins"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "coin_id", "exchange_account_id",
            name="uq_watchlist_user_coin_account",
        ),
        Index("ix_watchlist_coins_user_id_sort_order", "user_id", "sort_order"),
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
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="watchlist_coins")
    coin: Mapped["Coin"] = relationship("Coin", back_populates="watchlist_coins")
    exchange_account: Mapped["UserExchangeAccount | None"] = relationship(
        "UserExchangeAccount", back_populates="watchlist_coins"
    )
    ai_trading_config: Mapped["AiTradingConfig | None"] = relationship(
        "AiTradingConfig", back_populates="watchlist_coin", uselist=False
    )
