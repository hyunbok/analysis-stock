"""소셜 로그인 API 엔드포인트 — Google, Apple OAuth2."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.core.deps import OAuthVerificationServiceDep, SocialAuthServiceDep
from app.schemas.auth import UserResponse
from app.schemas.common import ApiResponse
from app.schemas.social_auth import (
    AppleSocialLoginRequest,
    GoogleSocialLoginRequest,
    SocialLoginResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/google",
    response_model=ApiResponse[SocialLoginResponse],
    summary="Google 소셜 로그인",
    description="Google OAuth2 id_token 검증 후 JWT 발급. 신규 사용자는 자동 가입 처리.",
)
async def google_social_login(
    body: GoogleSocialLoginRequest,
    oauth_svc: OAuthVerificationServiceDep,
    social_auth: SocialAuthServiceDep,
) -> ApiResponse[SocialLoginResponse]:
    oauth_info = await oauth_svc.verify_google_token(body.id_token)
    user, tokens, is_new_user = await social_auth.social_login(oauth_info)
    return ApiResponse(data=SocialLoginResponse(
        user=UserResponse.from_user(user),
        tokens=tokens,
        is_new_user=is_new_user,
    ))


@router.post(
    "/apple",
    response_model=ApiResponse[SocialLoginResponse],
    summary="Apple 소셜 로그인",
    description="Apple Sign In id_token 검증 후 JWT 발급. 최초 로그인 시 user 정보 포함.",
)
async def apple_social_login(
    body: AppleSocialLoginRequest,
    oauth_svc: OAuthVerificationServiceDep,
    social_auth: SocialAuthServiceDep,
) -> ApiResponse[SocialLoginResponse]:
    oauth_info = await oauth_svc.verify_apple_token(body.id_token)
    user, tokens, is_new_user = await social_auth.social_login(
        oauth_info, apple_user=body.user
    )
    return ApiResponse(data=SocialLoginResponse(
        user=UserResponse.from_user(user),
        tokens=tokens,
        is_new_user=is_new_user,
    ))
