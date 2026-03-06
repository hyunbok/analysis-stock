"""인증 API 엔드포인트 — 회원가입, 이메일 인증, 로그인, 토큰 갱신, 로그아웃."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.core.deps import AuthServiceDep, CurrentUser
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    UserResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.schemas.common import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/register",
    response_model=ApiResponse[RegisterResponse],
    status_code=201,
    summary="회원가입",
    description="이메일, 비밀번호, 닉네임으로 가입 후 인증 코드를 이메일로 발송합니다.",
)
async def register(
    body: RegisterRequest,
    auth_svc: AuthServiceDep,
) -> ApiResponse[RegisterResponse]:
    await auth_svc.register(
        email=body.email,
        password=body.password,
        nickname=body.nickname,
    )
    return ApiResponse(data=RegisterResponse(email=body.email))


@router.post(
    "/verify-email",
    response_model=ApiResponse[VerifyEmailResponse],
    summary="이메일 인증 코드 확인",
    description="이메일로 발송된 6자리 인증 코드를 검증합니다.",
)
async def verify_email(
    body: VerifyEmailRequest,
    auth_svc: AuthServiceDep,
) -> ApiResponse[VerifyEmailResponse]:
    await auth_svc.verify_email(email=body.email, code=body.code)
    return ApiResponse(data=VerifyEmailResponse())


@router.post(
    "/login",
    response_model=ApiResponse[LoginResponse],
    summary="로그인",
    description="이메일/비밀번호 인증 후 Access + Refresh 토큰을 발급합니다.",
)
async def login(
    body: LoginRequest,
    auth_svc: AuthServiceDep,
) -> ApiResponse[LoginResponse]:
    user, tokens = await auth_svc.login(email=body.email, password=body.password)
    user_resp = UserResponse.from_user(user)
    return ApiResponse(data=LoginResponse(user=user_resp, tokens=tokens))


@router.post(
    "/refresh",
    response_model=ApiResponse[RefreshResponse],
    summary="토큰 갱신",
    description="Refresh Token으로 새 Access + Refresh 토큰 쌍을 발급합니다 (Rotation).",
)
async def refresh_tokens(
    body: RefreshRequest,
    auth_svc: AuthServiceDep,
) -> ApiResponse[RefreshResponse]:
    tokens = await auth_svc.refresh_tokens(body.refresh_token)
    return ApiResponse(data=RefreshResponse(tokens=tokens))


@router.post(
    "/logout",
    response_model=ApiResponse[LogoutResponse],
    summary="로그아웃",
    description="현재 세션의 Refresh Token을 폐기합니다.",
)
async def logout(
    body: LogoutRequest,
    current_user: CurrentUser,
    auth_svc: AuthServiceDep,
) -> ApiResponse[LogoutResponse]:
    await auth_svc.logout(
        user_id=str(current_user.id),
        refresh_token=body.refresh_token,
    )
    return ApiResponse(data=LogoutResponse())
