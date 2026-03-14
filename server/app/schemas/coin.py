"""코인 마스터 및 관심 코인 요청/응답 스키마."""
from __future__ import annotations

import math
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── Coin 응답 ──────────────────────────────────────────────────────────────────

class CoinResponse(BaseModel):
    """코인 마스터 응답 (실시간 시세 포함)."""

    id: uuid.UUID
    symbol: str
    name_ko: str | None
    name_en: str | None
    exchange_type: str
    market_code: str
    is_active: bool

    # 실시간 시세 (Redis ticker 스냅샷, 없으면 None — graceful degradation)
    current_price: Decimal | None = None
    change_rate_24h: Decimal | None = None
    volume_24h: Decimal | None = None
    open_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    price_updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CoinDetailResponse(CoinResponse):
    """코인 상세 응답 (CoinResponse + 메타 정보)."""

    created_at: datetime
    updated_at: datetime


class PaginatedCoins(BaseModel):
    """페이지네이션된 코인 목록."""

    items: list[CoinResponse]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def build(
        cls, items: list[CoinResponse], total: int, page: int, size: int
    ) -> "PaginatedCoins":
        pages = math.ceil(total / size) if size > 0 else 0
        return cls(items=items, total=total, page=page, size=size, pages=pages)


# ── 관심 코인 응답 ─────────────────────────────────────────────────────────────

class WatchlistCoinResponse(BaseModel):
    """관심 코인 응답."""

    id: uuid.UUID
    coin_id: uuid.UUID
    coin: CoinResponse
    exchange_account_id: uuid.UUID | None
    sort_order: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── 관심 코인 요청 ─────────────────────────────────────────────────────────────

class AddWatchlistRequest(BaseModel):
    """관심 코인 추가 요청."""

    coin_id: uuid.UUID
    exchange_account_id: uuid.UUID | None = None


class ReorderItem(BaseModel):
    """정렬 순서 변경 단건."""

    id: uuid.UUID
    sort_order: int = Field(ge=0)


class ReorderWatchlistRequest(BaseModel):
    """관심 코인 정렬 순서 변경 요청."""

    items: list[ReorderItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_sort_orders(self) -> "ReorderWatchlistRequest":
        orders = [item.sort_order for item in self.items]
        if len(orders) != len(set(orders)):
            raise ValueError("sort_order values must be unique")
        return self
