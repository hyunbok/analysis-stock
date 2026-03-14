"""관심 코인 DB 접근 계층 (PostgreSQL/AsyncSession)."""
from __future__ import annotations

import uuid

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.coin import WatchlistCoin


class WatchlistRepository:
    """WatchlistCoin 엔티티 DB 접근 계층."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, watchlist_id: uuid.UUID) -> WatchlistCoin | None:
        """selectinload(coin) 포함."""
        result = await self._db.execute(
            select(WatchlistCoin)
            .options(selectinload(WatchlistCoin.coin))
            .where(WatchlistCoin.id == watchlist_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_and_id(
        self, user_id: uuid.UUID, watchlist_id: uuid.UUID
    ) -> WatchlistCoin | None:
        """소유권 검증용. selectinload(coin) 포함."""
        result = await self._db.execute(
            select(WatchlistCoin)
            .options(selectinload(WatchlistCoin.coin))
            .where(
                WatchlistCoin.id == watchlist_id,
                WatchlistCoin.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_ids(self, ids: list[uuid.UUID]) -> list[WatchlistCoin]:
        if not ids:
            return []
        result = await self._db.execute(
            select(WatchlistCoin)
            .options(selectinload(WatchlistCoin.coin))
            .where(WatchlistCoin.id.in_(ids))
        )
        return list(result.scalars().all())

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID | None = None,
    ) -> list[WatchlistCoin]:
        """selectinload(coin) 포함, ORDER BY sort_order ASC.

        exchange_account_id 제공 시: 해당 계정 필터.
        미제공 시: 사용자 전체.
        """
        stmt = (
            select(WatchlistCoin)
            .options(selectinload(WatchlistCoin.coin))
            .where(WatchlistCoin.user_id == user_id)
        )
        if exchange_account_id is not None:
            stmt = stmt.where(
                WatchlistCoin.exchange_account_id == exchange_account_id
            )
        stmt = stmt.order_by(WatchlistCoin.sort_order.asc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_max_sort_order(self, user_id: uuid.UUID) -> int:
        """SELECT COALESCE(MAX(sort_order), -1). +1해서 신규 순서 결정."""
        result = await self._db.execute(
            select(func.coalesce(func.max(WatchlistCoin.sort_order), -1)).where(
                WatchlistCoin.user_id == user_id
            )
        )
        return result.scalar_one()

    async def create_or_conflict(
        self,
        user_id: uuid.UUID,
        coin_id: uuid.UUID,
        exchange_account_id: uuid.UUID | None,
        sort_order: int,
    ) -> WatchlistCoin | None:
        """ON CONFLICT DO NOTHING — rowcount 0이면 중복. 성공 시 WatchlistCoin 반환."""
        stmt = (
            pg_insert(WatchlistCoin)
            .values(
                user_id=user_id,
                coin_id=coin_id,
                exchange_account_id=exchange_account_id,
                sort_order=sort_order,
            )
            .on_conflict_do_nothing(constraint="uq_watchlist_user_coin_account")
        )
        result = await self._db.execute(stmt)
        if result.rowcount == 0:
            return None
        await self._db.flush()

        # 방금 삽입된 레코드 조회 (selectinload 포함)
        fetch_result = await self._db.execute(
            select(WatchlistCoin)
            .options(selectinload(WatchlistCoin.coin))
            .where(
                WatchlistCoin.user_id == user_id,
                WatchlistCoin.coin_id == coin_id,
                WatchlistCoin.exchange_account_id == exchange_account_id
                if exchange_account_id is not None
                else WatchlistCoin.exchange_account_id.is_(None),
            )
        )
        return fetch_result.scalar_one_or_none()

    async def delete(self, watchlist_id: uuid.UUID) -> None:
        await self._db.execute(
            delete(WatchlistCoin).where(WatchlistCoin.id == watchlist_id)
        )
        await self._db.flush()

    async def bulk_update_sort_order(
        self,
        user_id: uuid.UUID,
        items: list[tuple[uuid.UUID, int]],
    ) -> None:
        """SQLAlchemy case() + update() — CASE WHEN 배치 단일 쿼리.

        UPDATE watchlist_coins
        SET sort_order = CASE id WHEN :id1 THEN :order1 ... END
        WHERE id = ANY(:ids) AND user_id = :user_id
        """
        if not items:
            return

        id_list = [item[0] for item in items]
        order_map = {id_: order for id_, order in items}

        stmt = (
            update(WatchlistCoin)
            .where(
                WatchlistCoin.id.in_(id_list),
                WatchlistCoin.user_id == user_id,
            )
            .values(
                sort_order=case(order_map, value=WatchlistCoin.id)
            )
        )
        await self._db.execute(stmt)
        await self._db.flush()
