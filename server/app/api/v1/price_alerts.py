"""가격 알림 CRUD API 엔드포인트."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.core.deps import CurrentUser, PriceAlertServiceDep
from app.schemas.common import ApiResponse
from app.schemas.price_alert import (
    CreatePriceAlertRequest,
    PriceAlertListResponse,
    PriceAlertResponse,
    UpdatePriceAlertRequest,
)

router = APIRouter()


@router.post(
    "", response_model=ApiResponse[PriceAlertResponse], status_code=status.HTTP_201_CREATED
)
async def create_price_alert(
    body: CreatePriceAlertRequest,
    current_user: CurrentUser,
    service: PriceAlertServiceDep,
) -> ApiResponse[PriceAlertResponse]:
    """가격 알림 생성. 사용자당 최대 50개."""
    result = await service.create_alert(current_user.id, body)
    return ApiResponse(data=result)


@router.get("", response_model=ApiResponse[PriceAlertListResponse])
async def list_price_alerts(
    current_user: CurrentUser,
    service: PriceAlertServiceDep,
    active: bool | None = Query(default=None, description="활성 알림 필터. None=전체"),
) -> ApiResponse[PriceAlertListResponse]:
    """가격 알림 목록 조회 + 미읽 알림 카운트."""
    result = await service.get_alerts(current_user.id, active=active)
    return ApiResponse(data=result)


@router.put("/{alert_id}", response_model=ApiResponse[PriceAlertResponse])
async def update_price_alert(
    alert_id: uuid.UUID,
    body: UpdatePriceAlertRequest,
    current_user: CurrentUser,
    service: PriceAlertServiceDep,
) -> ApiResponse[PriceAlertResponse]:
    """가격 알림 수정. 이미 트리거된 알림 재활성화 불가."""
    result = await service.update_alert(current_user.id, alert_id, body)
    return ApiResponse(data=result)


@router.delete("/{alert_id}", response_model=ApiResponse[None])
async def delete_price_alert(
    alert_id: uuid.UUID,
    current_user: CurrentUser,
    service: PriceAlertServiceDep,
) -> ApiResponse[None]:
    """가격 알림 삭제 (Hard Delete)."""
    await service.delete_alert(current_user.id, alert_id)
    return ApiResponse(data=None)
