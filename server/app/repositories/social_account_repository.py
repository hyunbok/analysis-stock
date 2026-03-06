"""UserSocialAccount 엔티티 DB 접근 계층 (PostgreSQL/AsyncSession)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserSocialAccount


class SocialAccountRepository:
    """UserSocialAccount DB 접근 계층."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_provider_id(
        self, provider: str, provider_id: str
    ) -> UserSocialAccount | None:
        """provider + provider_id로 소셜 계정 조회.

        Args:
            provider: OAuth 공급자 ("google" | "apple").
            provider_id: 공급자 내 고유 사용자 ID (JWT sub).

        Returns:
            UserSocialAccount 또는 None.
        """
        result = await self._db.execute(
            select(UserSocialAccount).where(
                UserSocialAccount.provider == provider,
                UserSocialAccount.provider_id == provider_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID) -> list[UserSocialAccount]:
        """사용자의 모든 소셜 계정 조회.

        Args:
            user_id: 사용자 UUID.

        Returns:
            UserSocialAccount 목록.
        """
        result = await self._db.execute(
            select(UserSocialAccount).where(UserSocialAccount.user_id == user_id)
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: uuid.UUID,
        provider: str,
        provider_id: str,
        provider_email: str | None,
    ) -> UserSocialAccount:
        """소셜 계정 연동 레코드 생성.

        Args:
            user_id: 연결할 사용자 UUID.
            provider: OAuth 공급자 ("google" | "apple").
            provider_id: 공급자 내 고유 사용자 ID (JWT sub).
            provider_email: 공급자에서 제공한 이메일 (없으면 None).

        Returns:
            생성된 UserSocialAccount 인스턴스.
        """
        social_account = UserSocialAccount(
            user_id=user_id,
            provider=provider,
            provider_id=provider_id,
            provider_email=provider_email,
        )
        self._db.add(social_account)
        await self._db.flush()
        await self._db.refresh(social_account)
        return social_account
