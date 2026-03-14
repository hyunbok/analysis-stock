"""코인 검색/상세 API 통합 테스트 — GET /coins, GET /coins/{coin_id}."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import CoinErrors
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.schemas.coin import CoinDetailResponse, CoinResponse, PaginatedCoins


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_coin_response(
    symbol: str = "BTC",
    name_ko: str | None = "비트코인",
    name_en: str | None = "Bitcoin",
    exchange_type: str = "upbit",
    market_code: str = "KRW-BTC",
    is_active: bool = True,
    current_price: Decimal | None = None,
) -> CoinResponse:
    return CoinResponse(
        id=uuid.uuid4(),
        symbol=symbol,
        name_ko=name_ko,
        name_en=name_en,
        exchange_type=exchange_type,
        market_code=market_code,
        is_active=is_active,
        current_price=current_price,
    )


def _make_coin_detail(
    symbol: str = "BTC",
    exchange_type: str = "upbit",
    current_price: Decimal | None = Decimal("50000000"),
) -> CoinDetailResponse:
    now = datetime.now(UTC)
    return CoinDetailResponse(
        id=uuid.uuid4(),
        symbol=symbol,
        name_ko="비트코인",
        name_en="Bitcoin",
        exchange_type=exchange_type,
        market_code="KRW-BTC",
        is_active=True,
        current_price=current_price,
        change_rate_24h=Decimal("1.23"),
        volume_24h=Decimal("12345.67"),
        open_price=Decimal("49000000"),
        high_price=Decimal("51000000"),
        low_price=Decimal("48000000"),
        price_updated_at=now,
        created_at=now,
        updated_at=now,
    )


def _make_paginated(
    items: list[CoinResponse] | None = None,
    total: int = 1,
    page: int = 1,
    size: int = 20,
) -> PaginatedCoins:
    coins = items if items is not None else [_make_coin_response()]
    return PaginatedCoins.build(items=coins, total=total, page=page, size=size)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_coin_service() -> AsyncMock:
    return AsyncMock()


def _build_app(mock_coin_service: AsyncMock) -> FastAPI:
    """테스트용 FastAPI 앱 — coins 라우터 + service mock."""
    from app.api.v1.coins import router as coins_router
    from app.core.deps import get_coin_service, get_current_user_optional

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(coins_router, prefix="/coins")

    app.dependency_overrides[get_coin_service] = lambda: mock_coin_service
    # 인증 선택적 — 기본은 미인증 (None)
    app.dependency_overrides[get_current_user_optional] = lambda: None
    return app


@pytest.fixture
def test_app(mock_coin_service: AsyncMock) -> FastAPI:
    return _build_app(mock_coin_service)


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c


# ── GET /coins — 코인 검색 ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_search_coins_returns_200_with_paginated_list(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """검색 조건 없이 전체 목록 → 200 + 페이지네이션."""
    coins = [_make_coin_response("BTC"), _make_coin_response("ETH")]
    mock_coin_service.search_coins.return_value = _make_paginated(coins, total=2)

    resp = await client.get("/coins")

    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["size"] == 20
    assert len(data["items"]) == 2
    assert data["items"][0]["symbol"] == "BTC"


@pytest.mark.anyio
async def test_search_coins_with_q_filter(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """q=BTC 검색 → service에 query='BTC' 전달."""
    mock_coin_service.search_coins.return_value = _make_paginated(
        [_make_coin_response("BTC")], total=1
    )

    resp = await client.get("/coins?q=BTC")

    assert resp.status_code == 200
    mock_coin_service.search_coins.assert_called_once_with(
        query="BTC",
        exchange_type=None,
        is_active=True,
        page=1,
        size=20,
    )


@pytest.mark.anyio
async def test_search_coins_with_exchange_filter(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """exchange=upbit 필터 → service에 exchange_type='upbit' 전달."""
    mock_coin_service.search_coins.return_value = _make_paginated(
        [_make_coin_response(exchange_type="upbit")], total=1
    )

    resp = await client.get("/coins?exchange=upbit")

    assert resp.status_code == 200
    call_kwargs = mock_coin_service.search_coins.call_args.kwargs
    assert call_kwargs["exchange_type"] == "upbit"


@pytest.mark.anyio
async def test_search_coins_with_is_active_false_filter(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """is_active=false 필터 → service에 is_active=False 전달."""
    mock_coin_service.search_coins.return_value = _make_paginated([], total=0)

    resp = await client.get("/coins?is_active=false")

    assert resp.status_code == 200
    call_kwargs = mock_coin_service.search_coins.call_args.kwargs
    assert call_kwargs["is_active"] is False


@pytest.mark.anyio
async def test_search_coins_with_pagination(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """page=2&size=10 → service에 page=2, size=10 전달."""
    mock_coin_service.search_coins.return_value = _make_paginated(
        [], total=50, page=2, size=10
    )

    resp = await client.get("/coins?page=2&size=10")

    assert resp.status_code == 200
    call_kwargs = mock_coin_service.search_coins.call_args.kwargs
    assert call_kwargs["page"] == 2
    assert call_kwargs["size"] == 10


@pytest.mark.anyio
async def test_search_coins_empty_result(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """검색 결과 없음 → 200 + 빈 items."""
    mock_coin_service.search_coins.return_value = _make_paginated([], total=0)

    resp = await client.get("/coins?q=NONEXISTENT")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 0
    assert data["items"] == []
    assert data["pages"] == 0


@pytest.mark.anyio
async def test_search_coins_includes_ticker_data(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """시세 데이터 포함된 응답 → current_price 필드 확인."""
    coin = _make_coin_response("BTC", current_price=Decimal("50000000"))
    mock_coin_service.search_coins.return_value = _make_paginated([coin], total=1)

    resp = await client.get("/coins")

    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert item["current_price"] is not None


@pytest.mark.anyio
async def test_search_coins_ticker_absent_returns_null(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """Redis 시세 없는 경우 → current_price=None (graceful degradation)."""
    coin = _make_coin_response("BTC", current_price=None)
    mock_coin_service.search_coins.return_value = _make_paginated([coin], total=1)

    resp = await client.get("/coins")

    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert item["current_price"] is None


@pytest.mark.anyio
async def test_search_coins_size_over_100_returns_422(client: AsyncClient):
    """size=101 → 422 (Query 제약 le=100)."""
    resp = await client.get("/coins?size=101")

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_search_coins_page_zero_returns_422(client: AsyncClient):
    """page=0 → 422 (Query 제약 ge=1)."""
    resp = await client.get("/coins?page=0")

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_search_coins_q_too_long_returns_422(client: AsyncClient):
    """q 길이 초과(101자) → 422 (Query 제약 max_length=100)."""
    long_q = "A" * 101
    resp = await client.get(f"/coins?q={long_q}")

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_search_coins_response_has_meta_timestamp(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """성공 응답에 meta.timestamp 포함."""
    mock_coin_service.search_coins.return_value = _make_paginated([], total=0)

    resp = await client.get("/coins")

    assert "meta" in resp.json()
    assert "timestamp" in resp.json()["meta"]


# ── GET /coins/{coin_id} — 코인 상세 ─────────────────────────────────────────


@pytest.mark.anyio
async def test_get_coin_returns_200_with_detail(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """코인 상세 조회 → 200 + created_at/updated_at 포함."""
    detail = _make_coin_detail()
    mock_coin_service.get_coin.return_value = detail

    resp = await client.get(f"/coins/{detail.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["symbol"] == "BTC"
    assert data["exchange_type"] == "upbit"
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.anyio
async def test_get_coin_includes_ticker_fields(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """시세 필드 모두 포함 확인."""
    detail = _make_coin_detail(current_price=Decimal("50000000"))
    mock_coin_service.get_coin.return_value = detail

    resp = await client.get(f"/coins/{detail.id}")

    data = resp.json()["data"]
    assert data["current_price"] is not None
    assert data["change_rate_24h"] is not None
    assert data["volume_24h"] is not None
    assert data["open_price"] is not None
    assert data["high_price"] is not None
    assert data["low_price"] is not None


@pytest.mark.anyio
async def test_get_coin_not_found_returns_404(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """존재하지 않는 coin_id → 404 COIN_NOT_FOUND."""
    mock_coin_service.get_coin.side_effect = CoinErrors.not_found()

    resp = await client.get(f"/coins/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "COIN_NOT_FOUND"


@pytest.mark.anyio
async def test_get_coin_invalid_uuid_returns_422(client: AsyncClient):
    """유효하지 않은 UUID 형식 → 422."""
    resp = await client.get("/coins/not-a-valid-uuid")

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_get_coin_ticker_null_graceful_degradation(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """Redis 시세 없는 상세 조회 → 200 + price 필드 null."""
    detail = _make_coin_detail(current_price=None)
    mock_coin_service.get_coin.return_value = detail

    resp = await client.get(f"/coins/{detail.id}")

    assert resp.status_code == 200
    assert resp.json()["data"]["current_price"] is None
