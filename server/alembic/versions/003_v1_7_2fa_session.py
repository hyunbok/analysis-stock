"""v1-7: 2FA 세션 관리 - Client 확장 및 TOTP 백업 코드 테이블 추가

Revision ID: c3d4e5f6a7b2
Revises: b2c3d4e5f6a1
Create Date: 2026-03-06 00:00:00.000000

변경 사항:
  1. clients 테이블: device_name, user_agent, ip_address, device_fingerprint, is_active 컬럼 추가
  2. clients 테이블: (user_id, device_fingerprint) 복합 인덱스 추가
  3. user_totp_backup_codes 테이블 신규 생성
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b2"
down_revision: Union[str, None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. clients 테이블 컬럼 추가
    # -------------------------------------------------------------------------
    op.add_column("clients", sa.Column("device_name", sa.String(200), nullable=True))
    op.add_column("clients", sa.Column("user_agent", sa.String(500), nullable=True))
    op.add_column("clients", sa.Column("ip_address", sa.String(45), nullable=True))
    op.add_column("clients", sa.Column("device_fingerprint", sa.String(64), nullable=True))
    op.add_column(
        "clients",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )

    # -------------------------------------------------------------------------
    # 2. clients (user_id, device_fingerprint) 복합 인덱스
    #    CONCURRENTLY: 운영 중 잠금 없이 생성 가능
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_clients_user_fingerprint "
        "ON clients (user_id, device_fingerprint)"
    )

    # -------------------------------------------------------------------------
    # 3. user_totp_backup_codes 테이블 생성
    #    - 1회용 TOTP 비상 백업 코드 저장
    #    - code_hash: SHA-256(plaintext_code) hex 64자
    #    - is_used: 사용 여부 (사용 후 즉시 true 처리)
    # -------------------------------------------------------------------------
    op.create_table(
        "user_totp_backup_codes",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column(
            "is_used",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_totp_backup_codes_user_id",
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "ix_totp_backup_codes_user_id",
        "user_totp_backup_codes",
        ["user_id"],
    )


def downgrade() -> None:
    # 역순으로 롤백
    op.drop_index("ix_totp_backup_codes_user_id", table_name="user_totp_backup_codes")
    op.drop_table("user_totp_backup_codes")

    op.drop_index("ix_clients_user_fingerprint", table_name="clients")

    op.drop_column("clients", "is_active")
    op.drop_column("clients", "device_fingerprint")
    op.drop_column("clients", "ip_address")
    op.drop_column("clients", "user_agent")
    op.drop_column("clients", "device_name")
