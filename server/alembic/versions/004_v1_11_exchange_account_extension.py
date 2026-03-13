"""v1-11: 거래소 계정 관리 API - user_exchange_accounts 테이블 확장

Revision ID: d4e5f6a7b8c3
Revises: c3d4e5f6a7b2
Create Date: 2026-03-13 00:00:00.000000

변경 사항:
  1. user_exchange_accounts 테이블: nickname, is_verified, warning_level, verified_at 컬럼 추가
  2. warning_level CHECK 제약조건 추가 ('none' | 'warning' | 'critical')
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c3"
down_revision: Union[str, None] = "c3d4e5f6a7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. user_exchange_accounts 컬럼 추가
    # -------------------------------------------------------------------------
    op.add_column(
        "user_exchange_accounts",
        sa.Column("nickname", sa.String(50), nullable=True),
    )
    op.add_column(
        "user_exchange_accounts",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "user_exchange_accounts",
        sa.Column(
            "warning_level",
            sa.String(10),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
    )
    op.add_column(
        "user_exchange_accounts",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # -------------------------------------------------------------------------
    # 2. warning_level CHECK 제약조건
    #    허용값: 'none' | 'warning' | 'critical'
    # -------------------------------------------------------------------------
    op.create_check_constraint(
        "ck_exchange_account_warning_level",
        "user_exchange_accounts",
        "warning_level IN ('none', 'warning', 'critical')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_exchange_account_warning_level",
        "user_exchange_accounts",
        type_="check",
    )

    op.drop_column("user_exchange_accounts", "verified_at")
    op.drop_column("user_exchange_accounts", "warning_level")
    op.drop_column("user_exchange_accounts", "is_verified")
    op.drop_column("user_exchange_accounts", "nickname")
