"""관심 코인 CRUD API 통합 테스트 — GET/POST/DELETE/PUT /watchlist."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import CoinErrors
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.models.user import User
from app.schemas.coin import CoinResponse, WatchlistCoinResponse


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_user(user_id: uuid.UUID | None = None) -> User:
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.email = "test@example.com"
    user.nickname = "테스터"
    user.email_verified_at = datetime.now(UTC)
    user.soft_deleted_at = None
    return user


def _make_coin_response(
    symbol: str = "BTC",
    exchange_type: str = "upbit",
    current_price: Decimal | None = None,
) -> CoinResponse:
    return CoinResponse(
        id=uuid.uuid4(),
        symbol=symbol,
        name_ko="비트코인",
        name_en="Bitcoin",
        exchange_type=exchange_type,
        market_code=f"KRW-{symbol}",
        is_active=True,
        current_price=current_price,
    )


def _make_watchlist_item(
    user_id: uuid.UUID | None = None,
    coin_symbol: str = "BTC",
    exchange_account_id: uuid.UUID | None = None,
    sort_order: int = 0,
) -> WatchlistCoinResponse:
    return WatchlistCoinResponse(
        id=uuid.uuid4(),
        coin_id=uuid.uuid4(),
        coin=_make_coin_response(coin_symbol),
        exchange_account_id=exchange_account_id,
        sort_order=sort_order,
        created_at=datetime.now(UTC),
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_coin_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_user() -> User:
    return _make_user()


def _build_app(
    mock_coin_service: AsyncMock,
    current_user: User | None = None,
) -> FastAPI:
    """테스트용 FastAPI 앱 — watchlist 라우터 + 선택적 인증 override."""
    from app.api.v1.watchlist import router as watchlist_router
    from app.core.deps import get_coin_service, get_current_user

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(watchlist_router, prefix="/watchlist")

    app.dependency_overrides[get_coin_service] = lambda: mock_coin_service
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


@pytest.fixture
def test_app(mock_coin_service: AsyncMock, mock_user: User) -> FastAPI:
    """인증된 사용자 앱."""
    return _build_app(mock_coin_service, current_user=mock_user)


@pytest.fixture
def test_app_no_auth(mock_coin_service: AsyncMock) -> FastAPI:
    """인증 override 없는 앱 (401 테스트용)."""
    return _build_app(mock_coin_service, current_user=None)


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
async def anon_client(test_app_no_auth: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app_no_auth), base_url="http://test"
    ) as c:
        yield c


# ── 인증 필수 검증 ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_watchlist_unauthenticated_returns_401(anon_client: AsyncClient):
    """Authorization 없이 목록 조회 → 401."""
    resp = await anon_client.get("/watchlist")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_add_watchlist_unauthenticated_returns_401(anon_client: AsyncClient):
    """Authorization 없이 추가 → 401."""
    resp = await anon_client.post(
        "/watchlist",
        json={"coin_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_delete_watchlist_unauthenticated_returns_401(anon_client: AsyncClient):
    """Authorization 없이 삭제 → 401."""
    resp = await anon_client.delete(f"/watchlist/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_reorder_watchlist_unauthenticated_returns_401(anon_client: AsyncClient):
    """Authorization 없이 reorder → 401."""
    resp = await anon_client.put(
        "/watchlist/reorder",
        json={"items": [{"id": str(uuid.uuid4()), "sort_order": 0}]},
    )
    assert resp.status_code == 401


# ── GET /watchlist — 목록 조회 ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_watchlist_returns_200_with_list(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """관심 코인 목록 조회 → 200 + 배열 응답."""
    items = [
        _make_watchlist_item(sort_order=0),
        _make_watchlist_item(coin_symbol="ETH", sort_order=1),
    ]
    mock_coin_service.get_watchlist.return_value = items

    resp = await client.get("/watchlist")

    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["coin"]["symbol"] == "BTC"
    assert data[1]["coin"]["symbol"] == "ETH"


@pytest.mark.anyio
async def test_get_watchlist_empty_returns_empty_list(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """관심 코인 없을 때 → 200 + 빈 배열."""
    mock_coin_service.get_watchlist.return_value = []

    resp = await client.get("/watchlist")

    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.anyio
async def test_get_watchlist_with_exchange_account_filter(
    client: AsyncClient, mock_coin_service: AsyncMock, mock_user: User
):
    """exchange_account_id 필터 → service에 전달."""
    ea_id = uuid.uuid4()
    item = _make_watchlist_item(exchange_account_id=ea_id)
    mock_coin_service.get_watchlist.return_value = [item]

    resp = await client.get(f"/watchlist?exchange_account_id={ea_id}")

    assert resp.status_code == 200
    mock_coin_service.get_watchlist.assert_called_once_with(
        user_id=mock_user.id,
        exchange_account_id=ea_id,
    )


@pytest.mark.anyio
async def test_get_watchlist_item_has_required_fields(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """응답 아이템에 필수 필드 포함 확인."""
    item = _make_watchlist_item()
    mock_coin_service.get_watchlist.return_value = [item]

    resp = await client.get("/watchlist")

    data = resp.json()["data"]
    first = data[0]
    assert "id" in first
    assert "coin_id" in first
    assert "coin" in first
    assert "sort_order" in first
    assert "created_at" in first
    assert "exchange_account_id" in first


@pytest.mark.anyio
async def test_get_watchlist_passes_user_id(
    client: AsyncClient, mock_coin_service: AsyncMock, mock_user: User
):
    """service.get_watchlist()에 현재 사용자 ID 전달."""
    mock_coin_service.get_watchlist.return_value = []

    await client.get("/watchlist")

    mock_coin_service.get_watchlist.assert_called_once_with(
        user_id=mock_user.id,
        exchange_account_id=None,
    )


# ── POST /watchlist — 추가 ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_add_to_watchlist_returns_201(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """정상 추가 → 201 + 추가된 항목 반환."""
    coin_id = uuid.uuid4()
    item = _make_watchlist_item()
    mock_coin_service.add_to_watchlist.return_value = item

    resp = await client.post(
        "/watchlist",
        json={"coin_id": str(coin_id)},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    assert "id" in body["data"]
    assert "coin" in body["data"]


@pytest.mark.anyio
async def test_add_to_watchlist_with_exchange_account(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """exchange_account_id 포함 추가 → 201."""
    coin_id = uuid.uuid4()
    ea_id = uuid.uuid4()
    item = _make_watchlist_item(exchange_account_id=ea_id)
    mock_coin_service.add_to_watchlist.return_value = item

    resp = await client.post(
        "/watchlist",
        json={"coin_id": str(coin_id), "exchange_account_id": str(ea_id)},
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["exchange_account_id"] == str(ea_id)


@pytest.mark.anyio
async def test_add_to_watchlist_duplicate_returns_409(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """이미 추가된 코인 → 409 WATCHLIST_DUPLICATE."""
    mock_coin_service.add_to_watchlist.side_effect = CoinErrors.watchlist_duplicate()

    resp = await client.post(
        "/watchlist",
        json={"coin_id": str(uuid.uuid4())},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "WATCHLIST_DUPLICATE"


@pytest.mark.anyio
async def test_add_to_watchlist_coin_not_found_returns_404(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """존재하지 않는 coin_id → 404 COIN_NOT_FOUND."""
    mock_coin_service.add_to_watchlist.side_effect = CoinErrors.not_found()

    resp = await client.post(
        "/watchlist",
        json={"coin_id": str(uuid.uuid4())},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "COIN_NOT_FOUND"


@pytest.mark.anyio
async def test_add_to_watchlist_account_mismatch_returns_403(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """타인 소유 거래소 계정 → 403 EXCHANGE_ACCOUNT_MISMATCH."""
    mock_coin_service.add_to_watchlist.side_effect = (
        CoinErrors.exchange_account_mismatch()
    )

    resp = await client.post(
        "/watchlist",
        json={"coin_id": str(uuid.uuid4()), "exchange_account_id": str(uuid.uuid4())},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "EXCHANGE_ACCOUNT_MISMATCH"


@pytest.mark.anyio
async def test_add_to_watchlist_missing_coin_id_returns_422(client: AsyncClient):
    """coin_id 누락 → 422 (Pydantic 검증 오류)."""
    resp = await client.post("/watchlist", json={})

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_add_to_watchlist_invalid_coin_id_returns_422(client: AsyncClient):
    """유효하지 않은 UUID → 422."""
    resp = await client.post(
        "/watchlist",
        json={"coin_id": "not-a-uuid"},
    )

    assert resp.status_code == 422


# ── DELETE /watchlist/{id} — 제거 ────────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_watchlist_returns_200_with_message(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """정상 삭제 → 200 + message."""
    mock_coin_service.remove_from_watchlist.return_value = None

    resp = await client.delete(f"/watchlist/{uuid.uuid4()}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "message" in data
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_delete_watchlist_not_found_returns_404(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """존재하지 않는 watchlist_id → 404 WATCHLIST_NOT_FOUND."""
    mock_coin_service.remove_from_watchlist.side_effect = (
        CoinErrors.watchlist_not_found()
    )

    resp = await client.delete(f"/watchlist/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "WATCHLIST_NOT_FOUND"


@pytest.mark.anyio
async def test_delete_watchlist_passes_user_id_and_watchlist_id(
    client: AsyncClient, mock_coin_service: AsyncMock, mock_user: User
):
    """service.remove_from_watchlist()에 user_id, watchlist_id 전달."""
    watchlist_id = uuid.uuid4()
    mock_coin_service.remove_from_watchlist.return_value = None

    await client.delete(f"/watchlist/{watchlist_id}")

    mock_coin_service.remove_from_watchlist.assert_called_once_with(
        user_id=mock_user.id,
        watchlist_id=watchlist_id,
    )


@pytest.mark.anyio
async def test_delete_watchlist_invalid_uuid_returns_422(client: AsyncClient):
    """유효하지 않은 UUID → 422."""
    resp = await client.delete("/watchlist/not-a-uuid")

    assert resp.status_code == 422


# ── PUT /watchlist/reorder — 정렬 순서 변경 ──────────────────────────────────


@pytest.mark.anyio
async def test_reorder_watchlist_returns_200_with_updated_list(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """정렬 순서 변경 → 200 + 업데이트된 목록."""
    id1, id2 = uuid.uuid4(), uuid.uuid4()
    updated = [
        _make_watchlist_item(sort_order=0),
        _make_watchlist_item(coin_symbol="ETH", sort_order=1),
    ]
    mock_coin_service.reorder_watchlist.return_value = updated

    resp = await client.put(
        "/watchlist/reorder",
        json={
            "items": [
                {"id": str(id1), "sort_order": 0},
                {"id": str(id2), "sort_order": 1},
            ]
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 2


@pytest.mark.anyio
async def test_reorder_watchlist_access_denied_returns_403(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """타인 소유 ID 포함 → 403 WATCHLIST_ACCESS_DENIED."""
    mock_coin_service.reorder_watchlist.side_effect = (
        CoinErrors.watchlist_access_denied()
    )

    resp = await client.put(
        "/watchlist/reorder",
        json={"items": [{"id": str(uuid.uuid4()), "sort_order": 0}]},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "WATCHLIST_ACCESS_DENIED"


@pytest.mark.anyio
async def test_reorder_watchlist_duplicate_sort_order_returns_422(
    client: AsyncClient,
):
    """sort_order 중복 → 422 (Pydantic model_validator)."""
    id1, id2 = uuid.uuid4(), uuid.uuid4()

    resp = await client.put(
        "/watchlist/reorder",
        json={
            "items": [
                {"id": str(id1), "sort_order": 0},
                {"id": str(id2), "sort_order": 0},  # 중복!
            ]
        },
    )

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_reorder_watchlist_empty_items_returns_422(client: AsyncClient):
    """items=[] → 422 (min_length=1)."""
    resp = await client.put("/watchlist/reorder", json={"items": []})

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_reorder_watchlist_missing_body_returns_422(client: AsyncClient):
    """요청 바디 없음 → 422."""
    resp = await client.put("/watchlist/reorder", json={})

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_reorder_watchlist_negative_sort_order_returns_422(client: AsyncClient):
    """sort_order 음수 → 422 (ge=0)."""
    resp = await client.put(
        "/watchlist/reorder",
        json={"items": [{"id": str(uuid.uuid4()), "sort_order": -1}]},
    )

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_reorder_watchlist_passes_user_id(
    client: AsyncClient, mock_coin_service: AsyncMock, mock_user: User
):
    """service.reorder_watchlist()에 user_id 전달."""
    mock_coin_service.reorder_watchlist.return_value = []

    await client.put(
        "/watchlist/reorder",
        json={"items": [{"id": str(uuid.uuid4()), "sort_order": 0}]},
    )

    call_kwargs = mock_coin_service.reorder_watchlist.call_args.kwargs
    assert call_kwargs["user_id"] == mock_user.id


# ── 응답 포맷 공통 검증 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_successful_response_has_meta_timestamp(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """성공 응답에 meta.timestamp 포함 확인."""
    mock_coin_service.get_watchlist.return_value = []

    resp = await client.get("/watchlist")

    body = resp.json()
    assert "meta" in body
    assert "timestamp" in body["meta"]


@pytest.mark.anyio
async def test_error_response_format(
    client: AsyncClient, mock_coin_service: AsyncMock
):
    """에러 응답 포맷 — code, message 필드 존재 확인."""
    from app.core.exceptions import AppError

    mock_coin_service.get_watchlist.side_effect = AppError("TEST_CODE", "테스트 에러", 400)

    resp = await client.get("/watchlist")

    error = resp.json()["error"]
    assert "code" in error
    assert "message" in error
