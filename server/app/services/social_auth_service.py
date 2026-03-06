"""소셜 로그인 비즈니스 로직 오케스트레이션."""
from __future__ import annotations

import logging
import uuid

from app.core import security
from app.core.config import Settings
from app.core.exceptions import AuthErrors
from app.models.user import User
from app.repositories.social_account_repository import SocialAccountRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenPair
from app.schemas.social_auth import AppleUserData, OAuthUserInfo
from app.services.auth_cache_service import AuthCacheService

logger = logging.getLogger(__name__)


class SocialAuthService:
    """소셜 로그인 비즈니스 로직.

    id_token 검증은 OAuthVerificationService에서 수행.
    이 서비스는 OAuthUserInfo를 받아 DB 조회/생성/병합 + JWT 발급만 담당.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        social_repo: SocialAccountRepository,
        cache: AuthCacheService,
        settings: Settings,
    ) -> None:
        self._user_repo = user_repo
        self._social_repo = social_repo
        self._cache = cache
        self._settings = settings

    async def social_login(
        self,
        oauth_info: OAuthUserInfo,
        apple_user: AppleUserData | None = None,
    ) -> tuple[User, TokenPair, bool]:
        """소셜 로그인 처리 → (User, TokenPair, is_new_user) 반환.

        Args:
            oauth_info: OAuth 검증 서비스가 반환한 표준화된 사용자 정보.
            apple_user: Apple 최초 로그인 시 클라이언트가 전달한 사용자 데이터 (선택).

        Returns:
            (User, TokenPair, is_new_user) 튜플.

        Raises:
            AppError(ACCOUNT_DELETED): 이메일 병합 대상 계정이 삭제 예약 상태.

        처리 흐름:
            [A] social_repo.get_by_provider_id(provider, provider_id) → 존재
                → 연결된 User 로드 → JWT 발급 (is_new_user=False)
            [B] 소셜 계정 없음 + email 있음 + user_repo.get_by_email(email) → 존재
                → 소셜 계정 병합(UserSocialAccount 생성) → JWT 발급 (is_new_user=False)
                → 기존 User의 email_verified_at이 None이면 now()로 업데이트
            [C] 소셜 계정 없음 + 기존 User 없음
                → 신규 User 생성 + UserSocialAccount 생성 → JWT 발급 (is_new_user=True)
        """
        # [A] 기존 소셜 계정 조회
        social_account = await self._social_repo.get_by_provider_id(
            oauth_info.provider, oauth_info.provider_id
        )
        if social_account is not None:
            user = await self._user_repo.get_by_id(social_account.user_id)
            if user is None or user.soft_deleted_at is not None:
                raise AuthErrors.account_deleted()
            tokens = await self._issue_tokens(user)
            return user, tokens, False

        # [B] 이메일 기반 기존 계정 병합
        if oauth_info.email:
            existing_user = await self._user_repo.get_by_email(oauth_info.email)
            if existing_user is not None:
                if existing_user.soft_deleted_at is not None:
                    raise AuthErrors.account_deleted()
                await self._social_repo.create(
                    user_id=existing_user.id,
                    provider=oauth_info.provider,
                    provider_id=oauth_info.provider_id,
                    provider_email=oauth_info.email,
                )
                # 이메일 미인증 상태라면 소셜 로그인으로 인증 처리
                if existing_user.email_verified_at is None:
                    await self._user_repo.update_email_verified(existing_user.id)
                tokens = await self._issue_tokens(existing_user)
                return existing_user, tokens, False

        # [C] 신규 사용자 생성
        nickname = self._derive_nickname(oauth_info, apple_user)
        new_user = await self._user_repo.create_social_user(
            email=oauth_info.email or self._generate_placeholder_email(oauth_info),
            nickname=nickname,
            avatar_url=oauth_info.avatar_url,
        )
        await self._social_repo.create(
            user_id=new_user.id,
            provider=oauth_info.provider,
            provider_id=oauth_info.provider_id,
            provider_email=oauth_info.email,
        )
        tokens = await self._issue_tokens(new_user)
        return new_user, tokens, True

    async def _issue_tokens(self, user: User) -> TokenPair:
        """JWT Access + Refresh 발급 (AuthService.login 토큰 발급 패턴 동일)."""
        user_id_str = str(user.id)
        client_id = str(uuid.uuid4())

        access_token = security.create_access_token(user_id=user_id_str, email=user.email)
        refresh_token = security.create_refresh_token(user_id=user_id_str, client_id=client_id)
        token_hash = security.hash_token(refresh_token)

        await self._cache.store_refresh_token(user_id_str, client_id, token_hash)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @staticmethod
    def _derive_nickname(
        oauth_info: OAuthUserInfo, apple_user: AppleUserData | None
    ) -> str | None:
        """소셜 정보에서 초기 닉네임 도출. 없으면 None (온보딩에서 설정)."""
        # Apple: apple_user.name.last_name + first_name
        if apple_user and apple_user.name:
            parts = [
                apple_user.name.last_name or "",
                apple_user.name.first_name or "",
            ]
            name = "".join(parts).strip()
            if name:
                return name[:50]
        # Google: display_name 클레임
        if oauth_info.display_name:
            return oauth_info.display_name[:50]
        return None

    @staticmethod
    def _generate_placeholder_email(oauth_info: OAuthUserInfo) -> str:
        """Apple 이메일 없는 경우 내부 플레이스홀더 이메일 생성.

        실제 이메일 발송에 사용되지 않음 — DB unique 제약 만족용.
        """
        return f"{oauth_info.provider_id}@{oauth_info.provider}.social"
