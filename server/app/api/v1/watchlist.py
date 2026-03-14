"""관심 코인 CRUD API 엔드포인트."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.core.deps import CoinServiceDep, CurrentUser
from app.schemas.coin import (
    AddWatchlistRequest,
    ReorderWatchlistRequest,
    WatchlistCoinResponse,
)
from app.schemas.common import ApiResponse

router = APIRouter()


@router.get("", response_model=ApiResponse[list[WatchlistCoinResponse]])
async def get_watchlist(
    current_user: CurrentUser,
    service: CoinServiceDep,
    exchange_account_id: uuid.UUID | None = Query(
        default=None, description="거래소 계정 필터"
    ),
) -> ApiResponse[list[WatchlistCoinResponse]]:
    """관심 코인 목록 조회."""
    result = await service.get_watchlist(
        user_id=current_user.id,
        exchange_account_id=exchange_account_id,
    )
    return ApiResponse(data=result)


# NOTE: reorder를 {watchlist_id} 경로보다 먼저 등록 — "reorder"가 UUID로 캡처되는 문제 방지
@router.put("/reorder", response_model=ApiResponse[list[WatchlistCoinResponse]])
async def reorder_watchlist(
    body: ReorderWatchlistRequest,
    current_user: CurrentUser,
    service: CoinServiceDep,
) -> ApiResponse[list[WatchlistCoinResponse]]:
    """관심 코인 정렬 순서 변경."""
    result = await service.reorder_watchlist(
        user_id=current_user.id,
        items=body.items,
    )
    return ApiResponse(data=result)


@router.post("", response_model=ApiResponse[WatchlistCoinResponse], status_code=201)
async def add_to_watchlist(
    body: AddWatchlistRequest,
    current_user: CurrentUser,
    service: CoinServiceDep,
) -> ApiResponse[WatchlistCoinResponse]:
    """관심 코인 추가."""
    result = await service.add_to_watchlist(
        user_id=current_user.id,
        body=body,
    )
    return ApiResponse(data=result)


@router.delete(
    "/{watchlist_id}", response_model=ApiResponse[dict]
)
async def remove_from_watchlist(
    watchlist_id: uuid.UUID,
    current_user: CurrentUser,
    service: CoinServiceDep,
) -> ApiResponse[dict]:
    """관심 코인 제거."""
    await service.remove_from_watchlist(
        user_id=current_user.id,
        watchlist_id=watchlist_id,
    )
    return ApiResponse(data={"message": "관심 코인이 제거되었습니다."})
