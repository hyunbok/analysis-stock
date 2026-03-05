import uuid
from datetime import datetime

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class UserExchangeAccount(Base):
    __tablename__ = "user_exchange_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "exchange_type", name="uq_exchange_account_user_type"),
        Index("ix_user_exchange_accounts_user_id", "user_id"),
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
    exchange_type: Mapped[str] = mapped_column(String(20), nullable=False)
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    permissions: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        pg.BOOLEAN, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="exchange_accounts")
    watchlist_coins: Mapped[list["WatchlistCoin"]] = relationship(
        "WatchlistCoin", back_populates="exchange_account"
    )
    trade_orders: Mapped[list["TradeOrder"]] = relationship(
        "TradeOrder", back_populates="exchange_account"
    )
    price_alerts: Mapped[list["PriceAlert"]] = relationship(
        "PriceAlert", back_populates="exchange_account"
    )
