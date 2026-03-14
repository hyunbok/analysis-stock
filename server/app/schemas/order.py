"""주문 생성/조회/취소 API 요청 및 응답 스키마."""
from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.providers.enums import ExchangeType, OrderMethod, OrderSide, OrderStatus


class CreateOrderRequest(BaseModel):
    """주문 생성 요청."""

    exchange_account_id: UUID
    coin_id: UUID
    side: OrderSide
    method: OrderMethod
    quantity: Decimal | None = None  # 코인 수량 (LIMIT 필수, MARKET SELL 필수)
    amount: Decimal | None = None    # KRW 총액 (MARKET BUY 시 사용)
    price: Decimal | None = None     # 지정가 (LIMIT 필수)

    @model_validator(mode="after")
    def validate_order_params(self) -> Self:
        if self.method == OrderMethod.LIMIT:
            if self.price is None:
                raise ValueError("price required for LIMIT order")
            if self.quantity is None:
                raise ValueError("quantity required for LIMIT order")
            if self.price <= 0 or self.quantity <= 0:
                raise ValueError("price and quantity must be positive")
        elif self.method == OrderMethod.MARKET:
            if self.side == OrderSide.BUY:
                if self.amount is None:
                    raise ValueError("amount (KRW) required for MARKET BUY")
                if self.amount <= 0:
                    raise ValueError("amount must be positive")
            else:  # SELL
                if self.quantity is None:
                    raise ValueError("quantity required for MARKET SELL")
                if self.quantity <= 0:
                    raise ValueError("quantity must be positive")
        return self


class OrderResponse(BaseModel):
    """주문 단건 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    exchange_account_id: UUID
    coin_id: UUID
    coin_symbol: str
    exchange_type: ExchangeType
    side: OrderSide
    method: OrderMethod
    status: OrderStatus
    price: Decimal | None
    quantity: Decimal | None
    amount: Decimal | None
    executed_quantity: Decimal
    executed_price: Decimal | None
    fee: Decimal
    fee_rate: Decimal | None
    fee_currency: str | None
    exchange_order_id: str | None
    is_ai_order: bool
    created_at: datetime
    updated_at: datetime
    executed_at: datetime | None


class OrderListQuery(BaseModel):
    """주문 목록 조회 쿼리 파라미터."""

    exchange_account_id: UUID | None = None
    coin_id: UUID | None = None
    status: OrderStatus | None = None
    side: OrderSide | None = None
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class PaginatedOrders(BaseModel):
    """주문 목록 페이지네이션 응답."""

    items: list[OrderResponse]
    total: int
    page: int
    size: int
    pages: int  # ceil(total / size)

    @classmethod
    def build(
        cls,
        items: list[OrderResponse],
        total: int,
        page: int,
        size: int,
    ) -> PaginatedOrders:
        pages = max(1, math.ceil(total / size)) if total > 0 else 0
        return cls(items=items, total=total, page=page, size=size, pages=pages)


class BatchCancelRequest(BaseModel):
    """일괄 취소 요청."""

    order_ids: list[UUID] = Field(..., min_length=1, max_length=20)


class BatchCancelFailure(BaseModel):
    """일괄 취소 개별 실패 정보."""

    order_id: UUID
    reason: str


class BatchCancelResponse(BaseModel):
    """일괄 취소 응답."""

    success_count: int
    failed_count: int
    success_ids: list[UUID]
    failed: list[BatchCancelFailure]
