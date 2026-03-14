"""v1-13: 코인 검색 인덱스 추가 — name_ko/name_en trgm, exchange partial, watchlist 복합

Revision ID: e5f6a7b8c9d4
Revises: d4e5f6a7b8c3
Create Date: 2026-03-14 00:00:00.000000

변경 사항:
  1. coins.name_ko GIN trgm 인덱스 추가 (한국어명 검색)
  2. coins.name_en GIN trgm 인덱스 추가 (영문명 검색)
  3. coins(exchange_type) Partial 인덱스 추가 (WHERE is_active = true)
  4. watchlist_coins(user_id, exchange_account_id, sort_order) 복합 인덱스 추가
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d4"
down_revision: Union[str, None] = "d4e5f6a7b8c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. coins.name_ko GIN trgm (한국어명 검색)
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_coins_name_ko_trgm "
        "ON coins USING gin (name_ko gin_trgm_ops)"
    )

    # -------------------------------------------------------------------------
    # 2. coins.name_en GIN trgm (영문명 검색)
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_coins_name_en_trgm "
        "ON coins USING gin (name_en gin_trgm_ops)"
    )

    # -------------------------------------------------------------------------
    # 3. coins exchange_type Partial index (is_active = true 코인 필터 최적화)
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_coins_exchange_active "
        "ON coins (exchange_type) WHERE is_active = true"
    )

    # -------------------------------------------------------------------------
    # 4. watchlist_coins 복합 인덱스 (계정별 필터 + 정렬 커버)
    #    PG B-tree는 NULL 인덱싱 지원 → exchange_account_id IS NULL 케이스도 처리
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_watchlist_user_account_sort "
        "ON watchlist_coins (user_id, exchange_account_id, sort_order)"
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_user_account_sort", table_name="watchlist_coins")
    op.drop_index("ix_coins_exchange_active", table_name="coins")
    op.drop_index("ix_coins_name_en_trgm", table_name="coins")
    op.drop_index("ix_coins_name_ko_trgm", table_name="coins")
