"""TradeOrderEvent DB 모델 — 주문 상태 변경 이력 (전자금융거래법 5년 보존)."""
import uuid
from datetime import datetime

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class TradeOrderEvent(Base):
    __tablename__ = "trade_order_events"
    __table_args__ = (
        Index("ix_trade_order_events_order_id", "trade_order_id"),
        Index("ix_trade_order_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    trade_order_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("trade_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(30), nullable=False,
    )  # created, status_changed, filled, cancelled, failed, synced
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    trade_order: Mapped["TradeOrder"] = relationship(  # noqa: F821
        "TradeOrder", back_populates="events",
    )
