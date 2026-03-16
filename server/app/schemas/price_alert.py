"""가격 알림 요청/응답 스키마."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── 요청 ──────────────────────────────────────────────────────────────────────

class CreatePriceAlertRequest(BaseModel):
    coin_id: uuid.UUID
    exchange_account_id: uuid.UUID | None = None
    condition: Literal["above", "below"]
    target_price: Decimal = Field(gt=0, decimal_places=8)


class UpdatePriceAlertRequest(BaseModel):
    condition: Literal["above", "below"] | None = None
    target_price: Decimal | None = Field(default=None, gt=0, decimal_places=8)
    is_active: bool | None = None


# ── 응답 ──────────────────────────────────────────────────────────────────────

class PriceAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    coin_id: uuid.UUID
    coin_symbol: str
    coin_name_ko: str | None
    exchange_account_id: uuid.UUID | None
    condition: str
    target_price: Decimal
    is_triggered: bool
    is_active: bool
    triggered_at: datetime | None
    created_at: datetime


class PriceAlertListResponse(BaseModel):
    """GET /price-alerts 응답 — 알림 목록 + 미읽 카운트 통합."""
    alerts: list[PriceAlertResponse]
    unread_count: int
