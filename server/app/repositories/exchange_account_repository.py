"""거래소 계정 DB 접근 계층 (PostgreSQL/AsyncSession)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exchange import UserExchangeAccount


class ExchangeAccountRepository:
    """UserExchangeAccount 엔티티 DB 접근 계층."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        user_id: uuid.UUID,
        exchange_type: str,
        api_key_encrypted: bytes,
        api_secret_encrypted: bytes,
        permissions: list[str] | None = None,
        nickname: str | None = None,
        is_verified: bool = False,
        warning_level: str = "none",
        verified_at: datetime | None = None,
    ) -> UserExchangeAccount:
        account = UserExchangeAccount(
            user_id=user_id,
            exchange_type=exchange_type,
            api_key_encrypted=api_key_encrypted,
            api_secret_encrypted=api_secret_encrypted,
            permissions=permissions,
            nickname=nickname,
            is_verified=is_verified,
            warning_level=warning_level,
            verified_at=verified_at,
        )
        self._db.add(account)
        await self._db.flush()
        await self._db.refresh(account)
        return account

    async def get_by_id(self, account_id: uuid.UUID) -> UserExchangeAccount | None:
        result = await self._db.execute(
            select(UserExchangeAccount).where(UserExchangeAccount.id == account_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID) -> list[UserExchangeAccount]:
        result = await self._db.execute(
            select(UserExchangeAccount).where(
                UserExchangeAccount.user_id == user_id
            )
        )
        return list(result.scalars().all())

    async def get_by_user_and_exchange(
        self, user_id: uuid.UUID, exchange_type: str
    ) -> UserExchangeAccount | None:
        result = await self._db.execute(
            select(UserExchangeAccount).where(
                UserExchangeAccount.user_id == user_id,
                UserExchangeAccount.exchange_type == exchange_type,
            )
        )
        return result.scalar_one_or_none()

    async def update(
        self, account_id: uuid.UUID, **kwargs: object
    ) -> UserExchangeAccount:
        await self._db.execute(
            update(UserExchangeAccount)
            .where(UserExchangeAccount.id == account_id)
            .values(**kwargs, updated_at=datetime.now(UTC))
        )
        await self._db.flush()
        account = await self.get_by_id(account_id)
        if account is None:
            raise RuntimeError(f"Account {account_id} not found after update")
        return account

    async def delete(self, account_id: uuid.UUID) -> None:
        await self._db.execute(
            delete(UserExchangeAccount).where(UserExchangeAccount.id == account_id)
        )
        await self._db.flush()
