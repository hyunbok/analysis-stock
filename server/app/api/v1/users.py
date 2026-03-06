"""사용자 프로필 API 엔드포인트 — 내 정보 조회/수정/계정 삭제."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.core.deps import AuthServiceDep, CurrentUser
from app.schemas.auth import (
    AccountDeleteResponse,
    DeleteAccountRequest,
    ProfileResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.schemas.common import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/me",
    response_model=ApiResponse[ProfileResponse],
    summary="내 정보 조회",
    description="현재 인증된 사용자의 프로필 정보를 반환합니다.",
)
async def get_me(
    current_user: CurrentUser,
) -> ApiResponse[ProfileResponse]:
    user_resp = UserResponse.from_user(current_user)
    return ApiResponse(data=ProfileResponse(user=user_resp))


@router.put(
    "/me",
    response_model=ApiResponse[ProfileResponse],
    summary="프로필 수정",
    description="닉네임, 언어, 테마, 가격 색상 스타일을 수정합니다.",
)
async def update_profile(
    body: UpdateProfileRequest,
    current_user: CurrentUser,
    auth_svc: AuthServiceDep,
) -> ApiResponse[ProfileResponse]:
    updated_user = await auth_svc.update_profile(current_user.id, body)
    user_resp = UserResponse.from_user(updated_user)
    return ApiResponse(data=ProfileResponse(user=user_resp))


@router.delete(
    "/me",
    response_model=ApiResponse[AccountDeleteResponse],
    summary="계정 삭제 예약",
    description="계정 삭제를 예약합니다. 30일 후 영구 삭제되며, 모든 세션이 즉시 폐기됩니다.",
)
async def delete_account(
    body: DeleteAccountRequest,
    current_user: CurrentUser,
    auth_svc: AuthServiceDep,
) -> ApiResponse[AccountDeleteResponse]:
    # refresh_token으로 현재 세션 무효화 후 soft delete
    await auth_svc.logout(user_id=str(current_user.id), refresh_token=body.refresh_token)
    scheduled_delete_at = await auth_svc.delete_account(current_user.id)
    return ApiResponse(
        data=AccountDeleteResponse(scheduled_delete_at=scheduled_delete_at)
    )
