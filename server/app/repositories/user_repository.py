"""User 엔티티 DB 접근 계층 (PostgreSQL/AsyncSession)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserTotpBackupCode


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

    # ── 2FA 메서드 ────────────────────────────────────────────────────────────

    async def update_totp_secret(self, user_id: uuid.UUID, encrypted: bytes | None) -> None:
        """TOTP secret 암호화값 저장 (또는 삭제 시 None).

        Args:
            user_id: 사용자 UUID.
            encrypted: encrypt_totp_secret() 반환값 또는 None (비활성화).
        """
        await self._db.execute(
            update(User)
            .where(User.id == user_id)
            .values(totp_secret_encrypted=encrypted)
        )
        await self._db.flush()

    async def set_2fa_enabled(self, user_id: uuid.UUID, enabled: bool) -> None:
        """is_2fa_enabled 플래그 업데이트.

        Args:
            user_id: 사용자 UUID.
            enabled: True=활성화, False=비활성화.
        """
        await self._db.execute(
            update(User).where(User.id == user_id).values(is_2fa_enabled=enabled)
        )
        await self._db.flush()

    async def create_backup_codes(
        self, user_id: uuid.UUID, code_hashes: list[str]
    ) -> None:
        """백업 코드 해시 목록을 user_totp_backup_codes에 일괄 저장.

        Args:
            user_id: 사용자 UUID.
            code_hashes: hash_backup_code() 결과 리스트 (10개).
        """
        for code_hash in code_hashes:
            self._db.add(UserTotpBackupCode(user_id=user_id, code_hash=code_hash))
        await self._db.flush()

    async def get_unused_backup_code(
        self, user_id: uuid.UUID, code_hash: str
    ) -> UserTotpBackupCode | None:
        """미사용 백업 코드 조회 (해시 일치 + is_used=False).

        Args:
            user_id: 사용자 UUID.
            code_hash: SHA-256 해시 (64자 hex).

        Returns:
            UserTotpBackupCode 또는 None.
        """
        result = await self._db.execute(
            select(UserTotpBackupCode).where(
                UserTotpBackupCode.user_id == user_id,
                UserTotpBackupCode.code_hash == code_hash,
                UserTotpBackupCode.is_used.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def mark_backup_code_used(self, backup_code_id: uuid.UUID) -> None:
        """백업 코드를 사용 완료 처리 (is_used=True, used_at=now).

        Args:
            backup_code_id: UserTotpBackupCode.id.
        """
        now = datetime.now(timezone.utc)
        await self._db.execute(
            update(UserTotpBackupCode)
            .where(UserTotpBackupCode.id == backup_code_id)
            .values(is_used=True, used_at=now)
        )
        await self._db.flush()

    async def count_unused_backup_codes(self, user_id: uuid.UUID) -> int:
        """미사용 백업 코드 잔여 수 조회.

        Args:
            user_id: 사용자 UUID.

        Returns:
            미사용 코드 수 (0~10).
        """
        from sqlalchemy import func as sql_func

        result = await self._db.execute(
            select(sql_func.count()).where(
                UserTotpBackupCode.user_id == user_id,
                UserTotpBackupCode.is_used.is_(False),
            )
        )
        return result.scalar_one()

    async def delete_backup_codes(self, user_id: uuid.UUID) -> None:
        """사용자의 모든 백업 코드 삭제 (2FA 비활성화 시).

        Args:
            user_id: 사용자 UUID.
        """
        await self._db.execute(
            delete(UserTotpBackupCode).where(UserTotpBackupCode.user_id == user_id)
        )
        await self._db.flush()

    async def create_social_user(
        self,
        *,
        email: str,
        nickname: str | None = None,
        avatar_url: str | None = None,
    ) -> User:
        """소셜 로그인 전용 User 생성.

        Args:
            email: OAuth 공급자에서 확인된 이메일 (또는 플레이스홀더).
            nickname: 표시 이름 (없으면 None, 온보딩에서 설정).
            avatar_url: 프로필 이미지 URL (Google만 제공).

        Returns:
            생성된 User.

        특이사항:
            - password_hash=None (소셜 전용 계정, 비밀번호 로그인 불가)
            - email_verified_at=now() (OAuth가 이메일 검증 보장)
        """
        now = datetime.now(timezone.utc)
        user = User(
            email=email,
            password_hash=None,
            nickname=nickname,
            avatar_url=avatar_url,
            email_verified_at=now,
        )
        self._db.add(user)
        await self._db.flush()
        await self._db.refresh(user)
        return user
