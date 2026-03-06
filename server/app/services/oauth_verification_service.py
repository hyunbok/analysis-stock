"""OAuth 공급자 JWT 검증 서비스 — Google / Apple."""
from __future__ import annotations

import logging
from typing import Any

from jose import JWTError, jwt

from app.core.config import Settings
from app.core.exceptions import AppError, AuthErrors
from app.schemas.social_auth import OAuthUserInfo
from app.services.jwks_cache_service import JwksCacheService

logger = logging.getLogger(__name__)


class OAuthVerificationService:
    """Google/Apple OAuth2 id_token 검증 단일 구현체.

    provider별 차이(JWKS URL, issuer, audience, email 필수 여부)는
    _PROVIDER_CONFIG dict으로 관리. 검증 로직은 _verify_token()에서 공통 처리.
    """

    # SSRF 방지: JWKS URL 환경변수 노출 금지 — 클래스 상수 고정
    _PROVIDER_CONFIG: dict[str, dict[str, Any]] = {
        "google": {
            "jwks_url": "https://www.googleapis.com/oauth2/v3/certs",
            "issuers": frozenset({
                "accounts.google.com",
                "https://accounts.google.com",
            }),
            "require_email": True,
        },
        "apple": {
            "jwks_url": "https://appleid.apple.com/auth/keys",
            "issuers": frozenset({"https://appleid.apple.com"}),
            "require_email": False,
        },
    }

    def __init__(self, settings: Settings, jwks_cache: JwksCacheService) -> None:
        self._settings = settings
        self._jwks_cache = jwks_cache

    async def verify_google_token(self, id_token: str) -> OAuthUserInfo:
        """Google id_token RS256 검증 → OAuthUserInfo 반환.

        검증 항목: RS256 서명, iss, aud(google_allowed_audiences), exp, email_verified.

        Raises:
            AppError(INVALID_OAUTH_TOKEN): 서명/만료/iss/aud 불일치.
            AppError(OAUTH_EMAIL_REQUIRED): email 없음 또는 email_verified != true.
            AppError(OAUTH_PROVIDER_UNAVAILABLE): JWKS 서버 응답 실패 또는 Client ID 미설정.
        """
        if not self._settings.google_allowed_audiences:
            logger.error("oauth_google_client_id_not_configured")
            raise AuthErrors.oauth_provider_unavailable()

        payload = await self._verify_token(
            provider="google",
            id_token=id_token,
            allowed_audiences=self._settings.google_allowed_audiences,
        )
        if not payload.get("email") or not payload.get("email_verified"):
            raise AuthErrors.oauth_email_required()

        return OAuthUserInfo(
            provider="google",
            provider_id=payload["sub"],
            email=payload["email"],
            display_name=payload.get("name"),
            avatar_url=payload.get("picture"),
        )

    async def verify_apple_token(self, id_token: str) -> OAuthUserInfo:
        """Apple id_token RS256 검증 → OAuthUserInfo 반환.

        검증 항목: RS256 서명, iss, aud(apple_allowed_audiences), exp.
        email: private relay 이메일 허용, 없어도 허용.

        Raises:
            AppError(INVALID_OAUTH_TOKEN): 서명/만료/iss/aud 불일치.
            AppError(OAUTH_PROVIDER_UNAVAILABLE): JWKS 서버 응답 실패 또는 Bundle ID 미설정.
        """
        if not self._settings.apple_allowed_audiences:
            logger.error("oauth_apple_bundle_id_not_configured")
            raise AuthErrors.oauth_provider_unavailable()

        payload = await self._verify_token(
            provider="apple",
            id_token=id_token,
            allowed_audiences=self._settings.apple_allowed_audiences,
        )
        return OAuthUserInfo(
            provider="apple",
            provider_id=payload["sub"],
            email=payload.get("email"),
            display_name=None,
            avatar_url=None,
        )

    async def _verify_token(
        self,
        provider: str,
        id_token: str,
        allowed_audiences: list[str],
    ) -> dict[str, Any]:
        """공통 JWT 검증 로직: kid 추출 → JWKS 공개키 조회 → RS256 검증.

        Args:
            provider: "google" | "apple"
            id_token: 클라이언트로부터 받은 JWT.
            allowed_audiences: 허용할 aud 값 목록.

        Returns:
            검증된 JWT 페이로드 dict.

        Raises:
            AppError(INVALID_OAUTH_TOKEN): 검증 실패.
            AppError(OAUTH_PROVIDER_UNAVAILABLE): JWKS 조회 실패.
        """
        config = self._PROVIDER_CONFIG[provider]
        try:
            header = jwt.get_unverified_header(id_token)
            kid: str = header.get("kid", "")

            public_key = await self._jwks_cache.get_public_key(
                provider=provider,
                kid=kid,
                jwks_url=config["jwks_url"],
            )

            payload: dict[str, Any] = jwt.decode(
                id_token,
                public_key,
                algorithms=["RS256"],
                audience=allowed_audiences,
                issuer=list(config["issuers"]),
            )
        except AppError:
            raise
        except JWTError as e:
            logger.warning("oauth_token_invalid", extra={"provider": provider, "error": str(e)})
            raise AuthErrors.invalid_oauth_token()
        except Exception as e:
            logger.error("oauth_verify_unexpected", extra={"provider": provider, "error": str(e)})
            raise AuthErrors.invalid_oauth_token()

        return payload
