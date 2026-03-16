"""v1-21: 가격 알림 시스템 — price_alerts 확장

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e5
Create Date: 2026-03-16 00:00:00.000000

변경 사항:
  1. price_alerts.updated_at 컬럼 추가 (수정 API 감사 추적)
  2. ix_price_alerts_coin_active_untriggered 추가
     — coin_id 기준 partial index (백그라운드 감지 루프 전용)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f6a7b8c9d0e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. price_alerts.updated_at 컬럼 추가
    # -------------------------------------------------------------------------
    op.add_column(
        "price_alerts",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    # 기존 레코드 backfill: created_at 값으로 초기화
    op.execute("UPDATE price_alerts SET updated_at = created_at WHERE updated_at IS NULL")
    # nullable=False로 변경
    op.alter_column("price_alerts", "updated_at", nullable=False)

    # -------------------------------------------------------------------------
    # 2. coin_id 기준 partial 인덱스 추가 (백그라운드 감지 루프 전용)
    #    쿼리 패턴: WHERE coin_id = :id AND is_active = true AND is_triggered = false
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_price_alerts_coin_active_untriggered "
        "ON price_alerts (coin_id) "
        "WHERE is_active = true AND is_triggered = false"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_price_alerts_coin_active_untriggered"
    )
    op.drop_column("price_alerts", "updated_at")
