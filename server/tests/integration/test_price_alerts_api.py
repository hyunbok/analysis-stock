"""가격 알림 CRUD API 통합 테스트 — POST/GET/PUT/DELETE /api/v1/price-alerts.

설계서: docs/tasks/v1-21-price-alert-system-plan.md §4.1
패턴:  test_orders_api.py와 동일 — 서비스 계층 Mock + HTTP 검증
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import PriceAlertErrors
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.models.user import User
from app.schemas.price_alert import (
    PriceAlertListResponse,
    PriceAlertResponse,
)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_user(email: str = "test@example.com") -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.nickname = "테스터"
    user.email_verified_at = datetime.now(UTC)
    user.soft_deleted_at = None
    return user


def _make_alert_response(
    alert_id: uuid.UUID | None = None,
    condition: str = "above",
    target_price: Decimal = Decimal("85000000"),
    is_triggered: bool = False,
    is_active: bool = True,
    coin_symbol: str = "BTC/KRW",
) -> PriceAlertResponse:
    now = datetime.now(UTC)
    return PriceAlertResponse(
        id=alert_id or uuid.uuid4(),
        coin_id=uuid.uuid4(),
        coin_symbol=coin_symbol,
        coin_name_ko="비트코인",
        exchange_account_id=None,
        condition=condition,
        target_price=target_price,
        is_triggered=is_triggered,
        is_active=is_active,
        triggered_at=None,
        created_at=now,
    )


def _make_list_response(
    alerts: list[PriceAlertResponse] | None = None,
    unread_count: int = 0,
) -> PriceAlertListResponse:
    return PriceAlertListResponse(
        alerts=alerts or [],
        unread_count=unread_count,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_price_alert_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_user() -> User:
    return _make_user()


def _build_app(
    mock_service: AsyncMock,
    current_user: User | None = None,
) -> FastAPI:
    from app.api.v1.price_alerts import router as price_alerts_router
    from app.core.deps import get_current_user, get_price_alert_service

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(price_alerts_router, prefix="/price-alerts")

    app.dependency_overrides[get_price_alert_service] = lambda: mock_service
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


@pytest.fixture
def test_app(mock_price_alert_service: AsyncMock, mock_user: User) -> FastAPI:
    return _build_app(mock_price_alert_service, current_user=mock_user)


@pytest.fixture
def test_app_no_auth(mock_price_alert_service: AsyncMock) -> FastAPI:
    return _build_app(mock_price_alert_service, current_user=None)


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


# ── 인증 검증 ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_alert_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 알림 생성 → 401."""
    resp = await anon_client.post("/price-alerts", json={})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_list_alerts_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 목록 조회 → 401."""
    resp = await anon_client.get("/price-alerts")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_update_alert_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 수정 → 401."""
    resp = await anon_client.put(f"/price-alerts/{uuid.uuid4()}", json={})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_delete_alert_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 삭제 → 401."""
    resp = await anon_client.delete(f"/price-alerts/{uuid.uuid4()}")
    assert resp.status_code == 401


# ── POST /price-alerts — 알림 생성 ───────────────────────────────────────────


@pytest.mark.anyio
async def test_create_alert_returns_201(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """정상 알림 생성 → 201 + PriceAlertResponse."""
    expected = _make_alert_response(condition="above")
    mock_price_alert_service.create_alert.return_value = expected

    resp = await client.post(
        "/price-alerts",
        json={
            "coin_id": str(uuid.uuid4()),
            "condition": "above",
            "target_price": "85000000",
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["condition"] == "above"
    assert data["is_active"] is True
    assert data["is_triggered"] is False
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_create_alert_below_condition_returns_201(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """below 조건 알림 생성 → 201."""
    expected = _make_alert_response(condition="below")
    mock_price_alert_service.create_alert.return_value = expected

    resp = await client.post(
        "/price-alerts",
        json={
            "coin_id": str(uuid.uuid4()),
            "condition": "below",
            "target_price": "80000000",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["condition"] == "below"


@pytest.mark.anyio
async def test_create_alert_coin_not_found_returns_404(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """코인 미존재 → 404 PRICE_ALERT_COIN_NOT_FOUND."""
    mock_price_alert_service.create_alert.side_effect = (
        PriceAlertErrors.coin_not_found()
    )

    resp = await client.post(
        "/price-alerts",
        json={
            "coin_id": str(uuid.uuid4()),
            "condition": "above",
            "target_price": "85000000",
        },
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PRICE_ALERT_COIN_NOT_FOUND"


@pytest.mark.anyio
async def test_create_alert_account_not_owned_returns_403(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """타인 소유 거래소 계정 → 403 PRICE_ALERT_ACCOUNT_NOT_OWNED."""
    mock_price_alert_service.create_alert.side_effect = (
        PriceAlertErrors.exchange_account_not_owned()
    )

    resp = await client.post(
        "/price-alerts",
        json={
            "coin_id": str(uuid.uuid4()),
            "exchange_account_id": str(uuid.uuid4()),
            "condition": "above",
            "target_price": "85000000",
        },
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PRICE_ALERT_ACCOUNT_NOT_OWNED"


@pytest.mark.anyio
async def test_create_alert_max_exceeded_returns_400(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """알림 50개 초과 → 400 PRICE_ALERT_MAX_EXCEEDED."""
    mock_price_alert_service.create_alert.side_effect = (
        PriceAlertErrors.max_exceeded()
    )

    resp = await client.post(
        "/price-alerts",
        json={
            "coin_id": str(uuid.uuid4()),
            "condition": "above",
            "target_price": "85000000",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PRICE_ALERT_MAX_EXCEEDED"


@pytest.mark.anyio
async def test_create_alert_invalid_condition_returns_422(client: AsyncClient):
    """유효하지 않은 condition → 422."""
    resp = await client.post(
        "/price-alerts",
        json={
            "coin_id": str(uuid.uuid4()),
            "condition": "equal",  # 유효하지 않음
            "target_price": "85000000",
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_alert_zero_price_returns_422(client: AsyncClient):
    """target_price=0 → 422 (gt=0 제약)."""
    resp = await client.post(
        "/price-alerts",
        json={
            "coin_id": str(uuid.uuid4()),
            "condition": "above",
            "target_price": "0",
        },
    )
    assert resp.status_code == 422


# ── GET /price-alerts — 목록 조회 ────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_alerts_returns_200_with_list(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """알림 목록 조회 → 200 + alerts + unread_count."""
    alerts = [_make_alert_response(), _make_alert_response()]
    mock_price_alert_service.get_alerts.return_value = _make_list_response(
        alerts=alerts, unread_count=2
    )

    resp = await client.get("/price-alerts")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data["alerts"], list)
    assert len(data["alerts"]) == 2
    assert data["unread_count"] == 2
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_list_alerts_with_active_filter(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """active=true 필터 → 200."""
    mock_price_alert_service.get_alerts.return_value = _make_list_response()

    resp = await client.get("/price-alerts", params={"active": "true"})

    assert resp.status_code == 200
    mock_price_alert_service.get_alerts.assert_called_once()


@pytest.mark.anyio
async def test_list_alerts_empty_returns_empty_list(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """알림 없을 때 → 200 + 빈 목록."""
    mock_price_alert_service.get_alerts.return_value = _make_list_response()

    resp = await client.get("/price-alerts")

    assert resp.status_code == 200
    assert resp.json()["data"]["alerts"] == []


# ── PUT /price-alerts/{id} — 수정 ────────────────────────────────────────────


@pytest.mark.anyio
async def test_update_alert_returns_200(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """알림 수정 → 200 + 수정된 PriceAlertResponse."""
    updated = _make_alert_response(target_price=Decimal("90000000"))
    mock_price_alert_service.update_alert.return_value = updated

    resp = await client.put(
        f"/price-alerts/{uuid.uuid4()}",
        json={"target_price": "90000000"},
    )

    assert resp.status_code == 200
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_update_alert_not_found_returns_404(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """미존재 알림 수정 → 404."""
    mock_price_alert_service.update_alert.side_effect = (
        PriceAlertErrors.not_found()
    )

    resp = await client.put(
        f"/price-alerts/{uuid.uuid4()}",
        json={"target_price": "90000000"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PRICE_ALERT_NOT_FOUND"


@pytest.mark.anyio
async def test_update_alert_access_denied_returns_403(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """타인 알림 수정 → 403 PRICE_ALERT_ACCESS_DENIED."""
    mock_price_alert_service.update_alert.side_effect = (
        PriceAlertErrors.access_denied()
    )

    resp = await client.put(
        f"/price-alerts/{uuid.uuid4()}",
        json={"target_price": "90000000"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PRICE_ALERT_ACCESS_DENIED"


@pytest.mark.anyio
async def test_update_triggered_alert_reactivate_returns_409(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """이미 트리거된 알림 재활성화 → 409 PRICE_ALERT_ALREADY_TRIGGERED."""
    mock_price_alert_service.update_alert.side_effect = (
        PriceAlertErrors.already_triggered()
    )

    resp = await client.put(
        f"/price-alerts/{uuid.uuid4()}",
        json={"is_active": True},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PRICE_ALERT_ALREADY_TRIGGERED"


# ── DELETE /price-alerts/{id} — 삭제 ─────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_alert_returns_200(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """알림 삭제 → 200."""
    mock_price_alert_service.delete_alert.return_value = None

    resp = await client.delete(f"/price-alerts/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_delete_alert_not_found_returns_404(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """미존재 알림 삭제 → 404."""
    mock_price_alert_service.delete_alert.side_effect = PriceAlertErrors.not_found()

    resp = await client.delete(f"/price-alerts/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PRICE_ALERT_NOT_FOUND"


@pytest.mark.anyio
async def test_delete_alert_access_denied_returns_403(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """타인 알림 삭제 → 403."""
    mock_price_alert_service.delete_alert.side_effect = PriceAlertErrors.access_denied()

    resp = await client.delete(f"/price-alerts/{uuid.uuid4()}")

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PRICE_ALERT_ACCESS_DENIED"


# ── 응답 포맷 공통 검증 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_success_response_has_meta_timestamp(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """성공 응답에 meta.timestamp 포함."""
    mock_price_alert_service.get_alerts.return_value = _make_list_response()

    resp = await client.get("/price-alerts")

    assert "meta" in resp.json()
    assert "timestamp" in resp.json()["meta"]


@pytest.mark.anyio
async def test_response_has_required_alert_fields(
    client: AsyncClient, mock_price_alert_service: AsyncMock
):
    """알림 응답에 필수 필드 포함 확인."""
    alert = _make_alert_response()
    mock_price_alert_service.get_alerts.return_value = _make_list_response(
        alerts=[alert]
    )

    resp = await client.get("/price-alerts")

    item = resp.json()["data"]["alerts"][0]
    required = [
        "id", "coin_id", "coin_symbol", "condition",
        "target_price", "is_triggered", "is_active", "created_at",
    ]
    for field in required:
        assert field in item, f"필드 누락: {field}"
