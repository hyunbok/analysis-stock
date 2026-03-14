"""주문 실행 및 거래 API 엔드포인트."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.core.deps import AuditServiceDep, CurrentUser, OrderServiceDep
from app.providers.enums import OrderSide, OrderStatus
from app.schemas.common import ApiResponse
from app.schemas.order import (
    BatchCancelRequest,
    BatchCancelResponse,
    CreateOrderRequest,
    OrderListQuery,
    OrderResponse,
    PaginatedOrders,
)
from app.services.audit_service import AuditAction

router = APIRouter()


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# NOTE: /batch-cancel은 /{order_id}보다 먼저 등록하여 path 캡처 방지
@router.post("/batch-cancel", response_model=ApiResponse[BatchCancelResponse])
async def batch_cancel_orders(
    body: BatchCancelRequest,
    request: Request,
    current_user: CurrentUser,
    service: OrderServiceDep,
    audit: AuditServiceDep,
) -> ApiResponse[BatchCancelResponse]:
    """미체결 주문 일괄 취소."""
    result = await service.batch_cancel(current_user.id, body)
    if result.success_count > 0:
        await audit.log(
            action=AuditAction.ORDER_BATCH_CANCELLED,
            ip_address=_get_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
            user_id=current_user.id,
            details={
                "success_count": result.success_count,
                "failed_count": result.failed_count,
            },
        )
    return ApiResponse(data=result)


@router.post("", response_model=ApiResponse[OrderResponse], status_code=201)
async def create_order(
    body: CreateOrderRequest,
    request: Request,
    current_user: CurrentUser,
    service: OrderServiceDep,
    audit: AuditServiceDep,
) -> ApiResponse[OrderResponse]:
    """주문 생성 (시장가/지정가)."""
    order = await service.create_order(current_user.id, body)
    await audit.log(
        action=AuditAction.ORDER_CREATED,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={
            "order_id": str(order.id),
            "side": body.side.value,
            "method": body.method.value,
        },
    )
    return ApiResponse(data=order)


@router.get("", response_model=ApiResponse[PaginatedOrders])
async def list_orders(
    current_user: CurrentUser,
    service: OrderServiceDep,
    exchange_account_id: UUID | None = None,
    coin_id: UUID | None = None,
    status: OrderStatus | None = None,
    side: OrderSide | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> ApiResponse[PaginatedOrders]:
    """주문 내역 조회."""
    query = OrderListQuery(
        exchange_account_id=exchange_account_id,
        coin_id=coin_id,
        status=status,
        side=side,
        from_dt=from_dt,
        to_dt=to_dt,
        page=page,
        size=size,
    )
    result = await service.list_orders(current_user.id, query)
    return ApiResponse(data=result)


@router.get("/{order_id}", response_model=ApiResponse[OrderResponse])
async def get_order(
    order_id: UUID,
    current_user: CurrentUser,
    service: OrderServiceDep,
) -> ApiResponse[OrderResponse]:
    """주문 상세 조회."""
    order = await service.get_order(current_user.id, order_id)
    return ApiResponse(data=order)


@router.delete("/{order_id}", response_model=ApiResponse[OrderResponse])
async def cancel_order(
    order_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: OrderServiceDep,
    audit: AuditServiceDep,
) -> ApiResponse[OrderResponse]:
    """주문 취소."""
    order = await service.cancel_order(current_user.id, order_id)
    await audit.log(
        action=AuditAction.ORDER_CANCELLED,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={"order_id": str(order_id)},
    )
    return ApiResponse(data=order)
