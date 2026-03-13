"""거래소 계정 관리 API 엔드포인트."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from app.core.deps import AuditServiceDep, CurrentUser, ExchangeAccountServiceDep
from app.schemas.common import ApiResponse
from app.schemas.exchange import (
    ExchangeAccountResponse,
    ExchangeVerifyResponse,
    RegisterExchangeRequest,
    UpdateExchangeRequest,
)
from app.services.audit_service import AuditAction

router = APIRouter()


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("", response_model=ApiResponse[ExchangeAccountResponse], status_code=201)
async def register_exchange_account(
    body: RegisterExchangeRequest,
    request: Request,
    current_user: CurrentUser,
    service: ExchangeAccountServiceDep,
    audit: AuditServiceDep,
) -> ApiResponse[ExchangeAccountResponse]:
    """거래소 API 키 등록."""
    account = await service.register(
        user_id=current_user.id,
        exchange_type=body.exchange_type,
        api_key=body.api_key,
        api_secret=body.api_secret,
        nickname=body.nickname,
    )
    await audit.log(
        action=AuditAction.EXCHANGE_ACCOUNT_REGISTERED,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={"exchange_type": body.exchange_type.value},
    )
    return ApiResponse(data=account)


@router.get("", response_model=ApiResponse[list[ExchangeAccountResponse]])
async def list_exchange_accounts(
    current_user: CurrentUser,
    service: ExchangeAccountServiceDep,
) -> ApiResponse[list[ExchangeAccountResponse]]:
    """등록된 거래소 계정 목록 조회."""
    accounts = await service.list_accounts(user_id=current_user.id)
    return ApiResponse(data=accounts)


@router.put("/{account_id}", response_model=ApiResponse[ExchangeAccountResponse])
async def update_exchange_account(
    account_id: uuid.UUID,
    body: UpdateExchangeRequest,
    current_user: CurrentUser,
    service: ExchangeAccountServiceDep,
) -> ApiResponse[ExchangeAccountResponse]:
    """거래소 API 키 수정."""
    account = await service.update(
        user_id=current_user.id,
        account_id=account_id,
        api_key=body.api_key,
        api_secret=body.api_secret,
        nickname=body.nickname,
    )
    return ApiResponse(data=account)


@router.delete("/{account_id}", response_model=ApiResponse[dict])
async def delete_exchange_account(
    account_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    service: ExchangeAccountServiceDep,
    audit: AuditServiceDep,
) -> ApiResponse[dict]:
    """거래소 계정 삭제."""
    await service.delete(user_id=current_user.id, account_id=account_id)
    await audit.log(
        action=AuditAction.EXCHANGE_ACCOUNT_DELETED,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={"account_id": str(account_id)},
    )
    return ApiResponse(data={"message": "거래소 계정이 삭제되었습니다."})


@router.post("/{account_id}/verify", response_model=ApiResponse[ExchangeVerifyResponse])
async def verify_exchange_account(
    account_id: uuid.UUID,
    current_user: CurrentUser,
    service: ExchangeAccountServiceDep,
) -> ApiResponse[ExchangeVerifyResponse]:
    """저장된 API 키로 거래소 연결 검증."""
    result = await service.verify(user_id=current_user.id, account_id=account_id)
    return ApiResponse(data=result)
