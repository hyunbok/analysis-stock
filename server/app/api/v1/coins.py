"""코인 검색/상세 API 엔드포인트."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.core.deps import CoinServiceDep, CurrentUserOptional
from app.providers.enums import ExchangeType
from app.schemas.coin import CoinDetailResponse, PaginatedCoins
from app.schemas.common import ApiResponse

router = APIRouter()


@router.get("", response_model=ApiResponse[PaginatedCoins])
async def search_coins(
    _current_user: CurrentUserOptional,
    service: CoinServiceDep,
    q: str | None = Query(default=None, max_length=100, description="검색 키워드"),
    exchange: ExchangeType | None = Query(default=None, description="거래소 필터 (upbit, coinone)"),
    is_active: bool = Query(default=True, description="활성 상태 필터"),
    page: int = Query(default=1, ge=1, description="페이지 번호"),
    size: int = Query(default=20, ge=1, le=100, description="페이지 크기"),
) -> ApiResponse[PaginatedCoins]:
    """코인 검색 — 심볼/한글명/영문명 기반, 거래소 필터 지원."""
    result = await service.search_coins(
        query=q,
        exchange_type=exchange.value if exchange else None,
        is_active=is_active,
        page=page,
        size=size,
    )
    return ApiResponse(data=result)


@router.get("/{coin_id}", response_model=ApiResponse[CoinDetailResponse])
async def get_coin(
    coin_id: uuid.UUID,
    _current_user: CurrentUserOptional,
    service: CoinServiceDep,
) -> ApiResponse[CoinDetailResponse]:
    """코인 상세 조회."""
    result = await service.get_coin(coin_id)
    return ApiResponse(data=result)
