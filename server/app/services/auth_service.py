"""인증 비즈니스 로직 오케스트레이션."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError

from app.core import security
from app.core.config import Settings
from app.core.exceptions import AuthErrors
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenPair, UpdateProfileRequest
from app.services.auth_cache_service import AuthCacheService
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


class AuthService:
    """인증 비즈니스 로직."""

    def __init__(
        self,
        user_repo: UserRepository,
        cache: AuthCacheService,
        email_service: EmailService,
        settings: Settings,
    ) -> None:
        self._repo = user_repo
        self._cache = cache
        self._email = email_service
        self._settings = settings

    async def register(self, email: str, password: str, nickname: str) -> None:
        """회원가입: User 생성 → 인증 코드 발송.

        Args:
            email: 이메일 주소.
            password: 평문 비밀번호 (8자 이상).
            nickname: 닉네임 (2~50자).

        Raises:
            AppError(EMAIL_ALREADY_EXISTS): 이미 가입된 이메일.
            AppError(NICKNAME_TAKEN): 이미 사용 중인 닉네임.
            AppError(EMAIL_SEND_FAILED): 이메일 발송 실패.
        """
        if await self._repo.get_by_email(email) is not None:
            raise AuthErrors.email_already_exists()

        if await self._repo.get_by_nickname(nickname) is not None:
            raise AuthErrors.nickname_taken()

        password_hash = security.hash_password(password)
        await self._repo.create(email=email, password_hash=password_hash, nickname=nickname)

        code = security.generate_email_code()
        await self._cache.store_email_verify_code(email, code)
        await self._email.send_verification_code(email, code)

    async def verify_email(self, email: str, code: str) -> None:
        """이메일 인증 코드 확인.

        Args:
            email: 인증할 이메일 주소.
            code: 6자리 인증 코드.

        Raises:
            AppError(USER_NOT_FOUND): 해당 이메일 사용자 없음.
            AppError(EMAIL_ALREADY_VERIFIED): 이미 인증 완료.
            AppError(INVALID_VERIFY_CODE): 코드 불일치 또는 만료.
        """
        user = await self._repo.get_by_email(email)
        if user is None:
            raise AuthErrors.user_not_found()

        if user.email_verified_at is not None:
            raise AuthErrors.email_already_verified()

        verified = await self._cache.verify_email_code(email, code)
        if not verified:
            raise AuthErrors.invalid_verify_code()

        await self._repo.update_email_verified(user.id)

    # 타이밍 어택 방지용 더미 bcrypt 해시 (절대 실제 비밀번호와 일치하지 않음)
    _DUMMY_HASH = "$2b$12$dummyhashfortimingatk.EBpMEtf9JqBFvWv0RVsaHkOy4W"

    async def login(self, email: str, password: str) -> tuple[User, TokenPair]:
        """로그인: 자격증명 검증 → 토큰 발급.

        Args:
            email: 이메일 주소.
            password: 평문 비밀번호.

        Returns:
            (User, TokenPair) 튜플.

        Raises:
            AppError(LOGIN_RATE_LIMIT): 로그인 시도 횟수 초과 (5회/15분).
            AppError(INVALID_CREDENTIALS): 이메일/비밀번호 불일치.
            AppError(EMAIL_NOT_VERIFIED): 이메일 미인증.
            AppError(ACCOUNT_DELETED): 삭제 예약된 계정.
        """
        # Rate limit 체크 (DB 조회 전 — 부하 공격 차단)
        attempts = await self._cache.get_login_attempts(email)
        if attempts >= self._settings.RATE_LIMIT_LOGIN_MAX:
            raise AuthErrors.login_rate_limit()

        user = await self._repo.get_by_email(email)

        # 타이밍 어택 방지: 사용자 존재 여부와 무관하게 항상 bcrypt 수행
        stored_hash = user.password_hash if (user and user.password_hash) else self._DUMMY_HASH
        password_ok = security.verify_password(password, stored_hash)

        if not password_ok or user is None:
            await self._cache.increment_login_attempts(
                email, self._settings.RATE_LIMIT_LOGIN_WINDOW
            )
            logger.warning("login_failed", email_domain=email.split("@")[-1])
            raise AuthErrors.invalid_credentials()

        if user.soft_deleted_at is not None:
            raise AuthErrors.account_deleted()

        if user.email_verified_at is None:
            raise AuthErrors.email_not_verified()

        # 로그인 성공 시 실패 카운터 리셋 (성공 후 1회 실패로 즉시 잠금 방지)
        await self._cache.reset_login_attempts(email)

        user_id_str = str(user.id)
        client_id = str(uuid.uuid4())

        access_token = security.create_access_token(user_id=user_id_str, email=user.email)
        refresh_token = security.create_refresh_token(user_id=user_id_str, client_id=client_id)
        token_hash = security.hash_token(refresh_token)

        await self._cache.store_refresh_token(user_id_str, client_id, token_hash)

        tokens = TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
        return user, tokens

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Refresh Token 검증 → 새 토큰 쌍 발급 (토큰 로테이션).

        Args:
            refresh_token: 기존 Refresh JWT.

        Returns:
            새 TokenPair.

        Raises:
            AppError(INVALID_REFRESH_TOKEN): 토큰 불일치/만료/폐기.
        """
        try:
            payload = security.decode_refresh_token(refresh_token)
        except JWTError:
            raise AuthErrors.invalid_refresh_token()

        user_id: str = payload["sub"]
        client_id: str = payload["client_id"]

        stored_hash = await self._cache.get_refresh_token(user_id, client_id)
        if stored_hash is None:
            raise AuthErrors.invalid_refresh_token()

        incoming_hash = security.hash_token(refresh_token)
        if isinstance(stored_hash, bytes):
            stored_hash = stored_hash.decode()
        if incoming_hash != stored_hash:
            raise AuthErrors.invalid_refresh_token()

        # 기존 토큰 폐기 후 새 토큰 발급 (rotation)
        await self._cache.revoke_refresh_token(user_id, client_id)

        user = await self._repo.get_by_id(uuid.UUID(user_id))
        if user is None:
            raise AuthErrors.invalid_refresh_token()

        new_access = security.create_access_token(user_id=user_id, email=user.email)
        new_refresh = security.create_refresh_token(user_id=user_id, client_id=client_id)
        new_hash = security.hash_token(new_refresh)

        await self._cache.store_refresh_token(user_id, client_id, new_hash)

        return TokenPair(
            access_token=new_access,
            refresh_token=new_refresh,
            expires_in=self._settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def logout(self, user_id: str, refresh_token: str) -> None:
        """해당 세션의 Refresh Token 폐기.

        Args:
            user_id: 사용자 UUID 문자열.
            refresh_token: 로그아웃할 세션의 Refresh JWT.

        Raises:
            AppError(INVALID_REFRESH_TOKEN): 토큰 불일치/폐기됨.
        """
        try:
            payload = security.decode_refresh_token(refresh_token)
        except JWTError:
            raise AuthErrors.invalid_refresh_token()

        client_id: str = payload["client_id"]

        stored_hash = await self._cache.get_refresh_token(user_id, client_id)
        if stored_hash is None:
            raise AuthErrors.invalid_refresh_token()

        incoming_hash = security.hash_token(refresh_token)
        if isinstance(stored_hash, bytes):
            stored_hash = stored_hash.decode()
        if incoming_hash != stored_hash:
            raise AuthErrors.invalid_refresh_token()

        await self._cache.revoke_refresh_token(user_id, client_id)

    async def get_user_by_id(self, user_id: uuid.UUID) -> User:
        """user_id로 User 조회.

        Args:
            user_id: 사용자 UUID.

        Returns:
            User 인스턴스.

        Raises:
            AppError(USER_NOT_FOUND): 사용자 없음.
        """
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise AuthErrors.user_not_found()
        return user

    async def update_profile(self, user_id: uuid.UUID, data: UpdateProfileRequest) -> User:
        """프로필 수정.

        Args:
            user_id: 사용자 UUID.
            data: 수정할 프로필 데이터.

        Returns:
            업데이트된 User 인스턴스.

        Raises:
            AppError(USER_NOT_FOUND): 사용자 없음.
            AppError(NICKNAME_TAKEN): 이미 사용 중인 닉네임.
        """
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise AuthErrors.user_not_found()

        if data.nickname is not None and data.nickname != user.nickname:
            existing = await self._repo.get_by_nickname(data.nickname)
            if existing is not None:
                raise AuthErrors.nickname_taken()

        return await self._repo.update_profile(
            user_id,
            nickname=data.nickname,
            language=data.language,
            theme=data.theme,
            price_color_style=data.price_color_style,
        )

    async def delete_account(self, user_id: uuid.UUID) -> datetime:
        """계정 삭제 예약 (soft delete) + 모든 세션 폐기.

        Args:
            user_id: 사용자 UUID.

        Returns:
            scheduled_delete_at: 영구 삭제 예정 시각 (now + 30일).

        Raises:
            AppError(USER_NOT_FOUND): 사용자 없음.
        """
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise AuthErrors.user_not_found()

        await self._repo.soft_delete(user_id)
        await self._cache.revoke_all_sessions(str(user_id))

        scheduled_delete_at = datetime.now(timezone.utc) + timedelta(days=30)
        return scheduled_delete_at
