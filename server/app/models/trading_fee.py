"""TradingFee DB 모델 — 거래소별 기본 수수료율 저장."""
import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class TradingFee(Base):
    __tablename__ = "trading_fees"
    __table_args__ = (
        UniqueConstraint(
            "exchange_type", "fee_tier",
            name="uq_trading_fee_exchange_tier",
        ),
        CheckConstraint("fee_tier >= 0", name="ck_trading_fee_tier"),
        CheckConstraint(
            "maker_rate >= 0 AND taker_rate >= 0",
            name="ck_trading_fee_rates",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    exchange_type: Mapped[str] = mapped_column(String(20), nullable=False)
    fee_tier: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False,
    )
    maker_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    taker_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    min_volume_krw: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 0), nullable=True,
    )
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
