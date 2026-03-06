"""User 엔티티 DB 접근 계층 (PostgreSQL/AsyncSession)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """User 엔티티 DB 접근 계층."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, email: str, password_hash: str, nickname: str) -> User:
        """신규 User 생성 후 반환.

        Args:
            email: 이메일 주소.
            password_hash: bcrypt 해시.
            nickname: 닉네임.

        Returns:
            생성된 User 인스턴스.
        """
        user = User(email=email, password_hash=password_hash, nickname=nickname)
        self._db.add(user)
        await self._db.flush()
        await self._db.refresh(user)
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """UUID로 User 조회.

        Args:
            user_id: 사용자 UUID.

        Returns:
            User 또는 None.
        """
        result = await self._db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """이메일로 User 조회.

        Args:
            email: 이메일 주소.

        Returns:
            User 또는 None.
        """
        result = await self._db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_nickname(self, nickname: str) -> User | None:
        """닉네임으로 User 조회 (중복 확인용).

        Args:
            nickname: 닉네임.

        Returns:
            User 또는 None.
        """
        result = await self._db.execute(select(User).where(User.nickname == nickname))
        return result.scalar_one_or_none()

    async def update_email_verified(self, user_id: uuid.UUID) -> User:
        """email_verified_at = now() 업데이트.

        Args:
            user_id: 사용자 UUID.

        Returns:
            업데이트된 User 인스턴스.
        """
        now = datetime.now(timezone.utc)
        await self._db.execute(
            update(User).where(User.id == user_id).values(email_verified_at=now)
        )
        await self._db.flush()
        user = await self.get_by_id(user_id)
        if user is None:
            raise RuntimeError(f"User {user_id} not found after update")
        return user

    async def update_profile(
        self,
        user_id: uuid.UUID,
        *,
        nickname: str | None = None,
        language: str | None = None,
        theme: str | None = None,
        price_color_style: str | None = None,
    ) -> User:
        """프로필 필드 부분 업데이트. None 필드는 변경하지 않음.

        Args:
            user_id: 사용자 UUID.
            nickname: 새 닉네임 (선택).
            language: 언어 코드 (선택).
            theme: 테마 (선택).
            price_color_style: 가격 색상 스타일 (선택).

        Returns:
            업데이트된 User 인스턴스.
        """
        values: dict = {}
        if nickname is not None:
            values["nickname"] = nickname
        if language is not None:
            values["language"] = language
        if theme is not None:
            values["theme"] = theme
        if price_color_style is not None:
            values["price_color_style"] = price_color_style

        if values:
            await self._db.execute(
                update(User).where(User.id == user_id).values(**values)
            )
            await self._db.flush()

        user = await self.get_by_id(user_id)
        if user is None:
            raise RuntimeError(f"User {user_id} not found after update")
        return user

    async def soft_delete(self, user_id: uuid.UUID) -> User:
        """soft_deleted_at = now() 설정.

        Args:
            user_id: 사용자 UUID.

        Returns:
            업데이트된 User 인스턴스.
        """
        now = datetime.now(timezone.utc)
        await self._db.execute(
            update(User).where(User.id == user_id).values(soft_deleted_at=now)
        )
        await self._db.flush()
        user = await self.get_by_id(user_id)
        if user is None:
            raise RuntimeError(f"User {user_id} not found after update")
        return user
