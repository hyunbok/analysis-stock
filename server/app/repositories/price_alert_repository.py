"""가격 알림 DB 접근 계층 (PostgreSQL/AsyncSession)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.coin import Coin
from app.models.trading import PriceAlert


class PriceAlertRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        coin_id: uuid.UUID,
        exchange_account_id: uuid.UUID | None,
        condition: str,
        target_price,
    ) -> PriceAlert:
        """INSERT + flush + refresh. Coin eager load 포함."""
        alert = PriceAlert(
            user_id=user_id,
            coin_id=coin_id,
            exchange_account_id=exchange_account_id,
            condition=condition,
            target_price=target_price,
        )
        self._db.add(alert)
        await self._db.flush()
        await self._db.refresh(alert, ["coin"])
        return alert

    async def get_by_id(self, alert_id: uuid.UUID) -> PriceAlert | None:
        result = await self._db.execute(
            select(PriceAlert)
            .options(selectinload(PriceAlert.coin))
            .where(PriceAlert.id == alert_id)
        )
        return result.scalars().first()

    async def get_by_user_and_id(
        self, user_id: uuid.UUID, alert_id: uuid.UUID
    ) -> PriceAlert | None:
        """소유권 검증용."""
        result = await self._db.execute(
            select(PriceAlert)
            .options(selectinload(PriceAlert.coin))
            .where(PriceAlert.id == alert_id, PriceAlert.user_id == user_id)
        )
        return result.scalars().first()

    async def get_by_user(
        self, user_id: uuid.UUID, *, active: bool | None = None
    ) -> list[PriceAlert]:
        """ORDER BY created_at DESC. selectinload(coin) 포함.
        active=None: 전체, True: 활성만, False: 비활성만."""
        stmt = (
            select(PriceAlert)
            .options(selectinload(PriceAlert.coin))
            .where(PriceAlert.user_id == user_id)
            .order_by(PriceAlert.created_at.desc())
        )
        if active is not None:
            stmt = stmt.where(PriceAlert.is_active == active)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_user(self, user_id: uuid.UUID) -> int:
        """사용자 활성 알림 수 (max 50 체크용)."""
        result = await self._db.execute(
            select(func.count()).where(
                PriceAlert.user_id == user_id,
                PriceAlert.is_active == True,  # noqa: E712
            )
        )
        return result.scalar()

    async def get_active_untriggered_by_market(
        self, exchange_type: str, market_code: str
    ) -> list[PriceAlert]:
        """ix_price_alerts_coin_active_untriggered partial index 활용.
        PriceAlertMonitor에서 호출."""
        result = await self._db.execute(
            select(PriceAlert)
            .join(Coin, PriceAlert.coin_id == Coin.id)
            .options(selectinload(PriceAlert.coin))
            .where(
                Coin.exchange_type == exchange_type,
                Coin.market_code == market_code,
                PriceAlert.is_active == True,  # noqa: E712
                PriceAlert.is_triggered == False,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def mark_triggered(self, alert_id: uuid.UUID) -> bool:
        """UPDATE ... WHERE id=:id AND is_triggered=False.
        Returns: affected_rows > 0 (중복 트리거 방지 1차 방어)."""
        result = await self._db.execute(
            update(PriceAlert)
            .where(PriceAlert.id == alert_id, PriceAlert.is_triggered == False)  # noqa: E712
            .values(
                is_triggered=True,
                is_active=False,
                triggered_at=func.now(),
            )
        )
        await self._db.flush()
        return result.rowcount > 0

    async def update(self, alert: PriceAlert, **kwargs) -> PriceAlert:
        """동적 UPDATE."""
        for key, value in kwargs.items():
            setattr(alert, key, value)
        await self._db.flush()
        await self._db.refresh(alert, ["coin"])
        return alert

    async def delete(self, alert_id: uuid.UUID) -> None:
        """Hard DELETE."""
        alert = await self.get_by_id(alert_id)
        if alert:
            await self._db.delete(alert)
            await self._db.flush()
