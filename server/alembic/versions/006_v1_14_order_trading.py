"""v1-14: 주문 실행 및 거래 API — 상태 머신 확장, trading_fees, trade_order_events

Revision ID: f6a7b8c9d0e5
Revises: e5f6a7b8c9d4
Create Date: 2026-03-14 00:00:00.000000

변경 사항:
  1. trade_orders CHECK 제약 변경: status에 'open', 'failed' 추가
  2. trade_orders 컬럼 추가: amount, executed_price, fee_rate, fee_currency
  3. trade_orders.quantity nullable 변경
  4. 기존 ix_trade_orders_pending DROP + WHERE 조건 확장 재생성
  5. 신규 인덱스 3개: user_account_status_created, exchange_order_id unique partial, active
  6. trading_fees 테이블 CREATE + 초기 수수료 데이터 INSERT
  7. trade_order_events 테이블 CREATE
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e5"
down_revision: Union[str, None] = "e5f6a7b8c9d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. trade_orders.status CHECK 제약 변경 (open, failed 추가)
    # -------------------------------------------------------------------------
    op.execute("ALTER TABLE trade_orders DROP CONSTRAINT IF EXISTS ck_trade_orders_status")
    op.execute(
        "ALTER TABLE trade_orders ADD CONSTRAINT ck_trade_orders_status "
        "CHECK (status IN ('pending', 'open', 'filled', 'cancelled', 'partial', 'failed'))"
    )

    # -------------------------------------------------------------------------
    # 2. trade_orders 컬럼 추가
    # -------------------------------------------------------------------------
    op.add_column(
        "trade_orders",
        sa.Column("amount", sa.Numeric(20, 8), nullable=True),
    )
    op.add_column(
        "trade_orders",
        sa.Column("executed_price", sa.Numeric(20, 8), nullable=True),
    )
    op.add_column(
        "trade_orders",
        sa.Column("fee_rate", sa.Numeric(10, 6), nullable=True),
    )
    op.add_column(
        "trade_orders",
        sa.Column("fee_currency", sa.String(10), nullable=True),
    )

    # -------------------------------------------------------------------------
    # 3. trade_orders.quantity nullable 변경
    # -------------------------------------------------------------------------
    op.alter_column("trade_orders", "quantity", existing_type=sa.Numeric(20, 8), nullable=True)

    # -------------------------------------------------------------------------
    # 4. 기존 ix_trade_orders_pending DROP + WHERE 조건 확장 재생성
    # -------------------------------------------------------------------------
    op.drop_index("ix_trade_orders_pending", table_name="trade_orders")
    op.execute(
        "CREATE INDEX ix_trade_orders_pending ON trade_orders (user_id, created_at) "
        "WHERE status IN ('pending', 'open', 'partial')"
    )

    # -------------------------------------------------------------------------
    # 5. 신규 인덱스 3개
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_trade_orders_user_account_status_created "
        "ON trade_orders (user_id, exchange_account_id, status, created_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_trade_orders_exchange_order_id_unique "
        "ON trade_orders (exchange_account_id, exchange_order_id) "
        "WHERE exchange_order_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_trade_orders_active "
        "ON trade_orders (user_id, exchange_account_id) "
        "WHERE status IN ('pending', 'open', 'partial')"
    )

    # -------------------------------------------------------------------------
    # 6. trading_fees 테이블 CREATE
    # -------------------------------------------------------------------------
    op.create_table(
        "trading_fees",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("exchange_type", sa.String(20), nullable=False),
        sa.Column("fee_tier", sa.Integer, server_default=sa.text("0"), nullable=False),
        sa.Column("maker_rate", sa.Numeric(10, 6), nullable=False),
        sa.Column("taker_rate", sa.Numeric(10, 6), nullable=False),
        sa.Column("min_volume_krw", sa.Numeric(20, 0), nullable=True),
        sa.Column("description", sa.String(100), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "exchange_type", "fee_tier", name="uq_trading_fee_exchange_tier"
        ),
        sa.CheckConstraint("fee_tier >= 0", name="ck_trading_fee_tier"),
        sa.CheckConstraint(
            "maker_rate >= 0 AND taker_rate >= 0", name="ck_trading_fee_rates"
        ),
    )

    # 초기 수수료 데이터 INSERT
    op.execute(
        """
        INSERT INTO trading_fees (exchange_type, fee_tier, maker_rate, taker_rate, description)
        VALUES
            ('upbit',    0, 0.000500, 0.000500, '일반 (0.05%)'),
            ('coinone',  0, 0.000200, 0.000200, '포트폴리오 (0.02%)'),
            ('coinbase', 0, 0.006000, 0.006000, '일반 (0.6%)'),
            ('binance',  0, 0.001000, 0.001000, '일반 (0.1%)')
        """
    )

    # -------------------------------------------------------------------------
    # 7. trade_order_events 테이블 CREATE
    # -------------------------------------------------------------------------
    op.create_table(
        "trade_order_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "trade_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trade_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_trade_order_events_order_id", "trade_order_events", ["trade_order_id"]
    )
    op.create_index(
        "ix_trade_order_events_created_at", "trade_order_events", ["created_at"]
    )


def downgrade() -> None:
    # 역순으로 제거
    op.drop_index("ix_trade_order_events_created_at", table_name="trade_order_events")
    op.drop_index("ix_trade_order_events_order_id", table_name="trade_order_events")
    op.drop_table("trade_order_events")

    op.drop_table("trading_fees")

    op.drop_index("ix_trade_orders_active", table_name="trade_orders")
    op.drop_index("ix_trade_orders_exchange_order_id_unique", table_name="trade_orders")
    op.drop_index("ix_trade_orders_user_account_status_created", table_name="trade_orders")

    op.drop_index("ix_trade_orders_pending", table_name="trade_orders")
    op.execute(
        "CREATE INDEX ix_trade_orders_pending ON trade_orders (user_id, created_at) "
        "WHERE status = 'pending'"
    )

    op.alter_column("trade_orders", "quantity", existing_type=sa.Numeric(20, 8), nullable=False)

    op.drop_column("trade_orders", "fee_currency")
    op.drop_column("trade_orders", "fee_rate")
    op.drop_column("trade_orders", "executed_price")
    op.drop_column("trade_orders", "amount")

    op.execute("ALTER TABLE trade_orders DROP CONSTRAINT IF EXISTS ck_trade_orders_status")
    op.execute(
        "ALTER TABLE trade_orders ADD CONSTRAINT ck_trade_orders_status "
        "CHECK (status IN ('pending', 'filled', 'cancelled', 'partial'))"
    )
