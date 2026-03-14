"""코인 마스터 DB 접근 계층 (PostgreSQL/AsyncSession)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coin import Coin


class CoinRepository:
    """Coin 엔티티 DB 접근 계층."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, coin_id: uuid.UUID) -> Coin | None:
        result = await self._db.execute(
            select(Coin).where(Coin.id == coin_id)
        )
        return result.scalar_one_or_none()

    async def get_by_ids(self, coin_ids: list[uuid.UUID]) -> list[Coin]:
        if not coin_ids:
            return []
        result = await self._db.execute(
            select(Coin).where(Coin.id.in_(coin_ids))
        )
        return list(result.scalars().all())

    async def search(
        self,
        query: str | None,
        exchange_type: str | None,
        is_active: bool,
        page: int,
        size: int,
    ) -> tuple[list[Coin], int]:
        """GIN trgm 인덱스 활용 검색 + COUNT 동시 반환.

        q 있으면: symbol/name_ko/name_en ILIKE '%{q}%' OR 조건
        exchange_type 필터, is_active 필터 (partial index 활용)
        ORDER BY symbol ASC
        """
        base_stmt = select(Coin).where(Coin.is_active == is_active)

        if exchange_type:
            base_stmt = base_stmt.where(Coin.exchange_type == exchange_type)

        if query:
            like = f"%{query}%"
            base_stmt = base_stmt.where(
                or_(
                    Coin.symbol.ilike(like),
                    Coin.name_ko.ilike(like),
                    Coin.name_en.ilike(like),
                )
            )

        # COUNT
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._db.execute(count_stmt)
        total: int = total_result.scalar_one()

        # ITEMS
        offset = (page - 1) * size
        items_stmt = base_stmt.order_by(Coin.symbol.asc()).offset(offset).limit(size)
        items_result = await self._db.execute(items_stmt)
        coins = list(items_result.scalars().all())

        return coins, total

    async def upsert(
        self,
        *,
        symbol: str,
        exchange_type: str,
        market_code: str,
        name_ko: str | None = None,
        name_en: str | None = None,
        is_active: bool = True,
    ) -> Coin:
        """INSERT ... ON CONFLICT (exchange_type, market_code) DO UPDATE.

        seed_coins.py에서 사용.
        """
        stmt = (
            pg_insert(Coin)
            .values(
                symbol=symbol,
                exchange_type=exchange_type,
                market_code=market_code,
                name_ko=name_ko,
                name_en=name_en,
                is_active=is_active,
            )
            .on_conflict_do_update(
                constraint="uq_coin_exchange_market",
                set_={
                    "symbol": pg_insert(Coin).excluded.symbol,
                    "name_ko": pg_insert(Coin).excluded.name_ko,
                    "name_en": pg_insert(Coin).excluded.name_en,
                    "is_active": pg_insert(Coin).excluded.is_active,
                    "updated_at": func.now(),
                },
            )
            .returning(Coin)
        )
        result = await self._db.execute(stmt)
        await self._db.flush()
        return result.scalar_one()
