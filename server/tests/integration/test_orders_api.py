"""주문 실행 및 거래 API 통합 테스트 — POST/GET/DELETE /api/v1/orders.

설계서: docs/tasks/v1-14-order-execution-trading-api-plan.md
패턴:  test_exchanges_api.py와 동일 — 서비스 계층 Mock + HTTP 검증
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AppError, CoinErrors, ExchangeErrors, OrderErrors
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.models.user import User
from app.schemas.order import (
    BatchCancelFailure,
    BatchCancelResponse,
    OrderResponse,
    PaginatedOrders,
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


def _make_order_response(
    side: str = "buy",
    method: str = "market",
    status: str = "filled",
    coin_symbol: str = "BTC",
    exchange_type: str = "upbit",
    price: Decimal | None = None,
    quantity: Decimal | None = Decimal("0.001"),
    amount: Decimal | None = Decimal("100000"),
    executed_quantity: Decimal = Decimal("0.001"),
    executed_price: Decimal | None = Decimal("100000000"),
    fee: Decimal = Decimal("50"),
    fee_rate: Decimal | None = Decimal("0.0005"),
    fee_currency: str | None = "KRW",
    exchange_order_id: str | None = "upbit-order-abc123",
    is_ai_order: bool = False,
) -> OrderResponse:
    now = datetime.now(UTC)
    return OrderResponse(
        id=uuid.uuid4(),
        exchange_account_id=uuid.uuid4(),
        coin_id=uuid.uuid4(),
        coin_symbol=coin_symbol,
        exchange_type=exchange_type,
        side=side,
        method=method,
        status=status,
        price=price,
        quantity=quantity,
        amount=amount,
        executed_quantity=executed_quantity,
        executed_price=executed_price,
        fee=fee,
        fee_rate=fee_rate,
        fee_currency=fee_currency,
        exchange_order_id=exchange_order_id,
        is_ai_order=is_ai_order,
        created_at=now,
        updated_at=now,
        executed_at=now if status == "filled" else None,
    )


def _make_paginated_orders(
    items: list[OrderResponse] | None = None,
    total: int = 0,
    page: int = 1,
    size: int = 20,
) -> PaginatedOrders:
    items = items or []
    pages = max(1, -(-total // size)) if total > 0 else 1
    return PaginatedOrders(items=items, total=total, page=page, size=size, pages=pages)


def _make_batch_cancel_response(
    success_ids: list[uuid.UUID] | None = None,
    failed: list[BatchCancelFailure] | None = None,
) -> BatchCancelResponse:
    success_ids = success_ids or []
    failed = failed or []
    return BatchCancelResponse(
        success_count=len(success_ids),
        failed_count=len(failed),
        success_ids=success_ids,
        failed=failed,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_order_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_user() -> User:
    return _make_user()


@pytest.fixture
def mock_other_user() -> User:
    return _make_user(email="other@example.com")


def _build_app(
    mock_order_service: AsyncMock,
    current_user: User | None = None,
) -> FastAPI:
    """테스트용 FastAPI 앱 — orders 라우터 + 선택적 인증 override."""
    from app.api.v1.orders import router as orders_router
    from app.core.deps import get_audit_service, get_current_user, get_order_service

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(orders_router, prefix="/orders")

    mock_audit = AsyncMock()
    mock_audit.log.return_value = None

    app.dependency_overrides[get_order_service] = lambda: mock_order_service
    app.dependency_overrides[get_audit_service] = lambda: mock_audit
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


@pytest.fixture
def test_app(mock_order_service: AsyncMock, mock_user: User) -> FastAPI:
    """인증된 사용자 앱."""
    return _build_app(mock_order_service, current_user=mock_user)


@pytest.fixture
def test_app_no_auth(mock_order_service: AsyncMock) -> FastAPI:
    """인증 override 없는 앱 (401 테스트용)."""
    return _build_app(mock_order_service, current_user=None)


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
async def test_create_order_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 주문 생성 → 401."""
    resp = await anon_client.post("/orders", json={})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_list_orders_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 주문 목록 조회 → 401."""
    resp = await anon_client.get("/orders")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_get_order_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 주문 상세 조회 → 401."""
    resp = await anon_client.get(f"/orders/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_cancel_order_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 주문 취소 → 401."""
    resp = await anon_client.delete(f"/orders/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_batch_cancel_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 일괄 취소 → 401."""
    resp = await anon_client.post(
        "/orders/batch-cancel", json={"order_ids": [str(uuid.uuid4())]}
    )
    assert resp.status_code == 401


# ── POST /orders — 주문 생성 ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_market_buy_order_returns_201(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """시장가 매수 주문 생성 → 201 + OrderResponse."""
    expected = _make_order_response(side="buy", method="market", status="filled")
    mock_order_service.create_order.return_value = expected

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["side"] == "buy"
    assert data["method"] == "market"
    assert data["status"] == "filled"
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_create_market_sell_order_returns_201(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """시장가 매도 주문 생성 → 201."""
    expected = _make_order_response(side="sell", method="market", status="filled")
    mock_order_service.create_order.return_value = expected

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "sell",
            "method": "market",
            "quantity": "0.001",
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["side"] == "sell"
    assert data["method"] == "market"
    assert data["status"] == "filled"


@pytest.mark.anyio
async def test_create_limit_buy_order_returns_201(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """지정가 매수 주문 생성 → 201 + status=open (체결 대기)."""
    expected = _make_order_response(side="buy", method="limit", status="open")
    mock_order_service.create_order.return_value = expected

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "limit",
            "price": "95000000",
            "quantity": "0.001",
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["side"] == "buy"
    assert data["method"] == "limit"
    assert data["status"] == "open"


@pytest.mark.anyio
async def test_create_limit_sell_order_returns_201(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """지정가 매도 주문 생성 → 201 + status=open."""
    expected = _make_order_response(side="sell", method="limit", status="open")
    mock_order_service.create_order.return_value = expected

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "sell",
            "method": "limit",
            "price": "105000000",
            "quantity": "0.001",
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["side"] == "sell"
    assert data["method"] == "limit"
    assert data["status"] == "open"


@pytest.mark.anyio
async def test_create_order_response_has_fee_info(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """주문 응답에 수수료 정보 포함 확인 (fee, fee_rate, fee_currency)."""
    expected = _make_order_response(
        fee=Decimal("50"),
        fee_rate=Decimal("0.0005"),
        fee_currency="KRW",
    )
    mock_order_service.create_order.return_value = expected

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert "fee" in data
    assert "fee_rate" in data
    assert "fee_currency" in data
    assert data["fee_currency"] == "KRW"
    assert Decimal(data["fee"]) == Decimal("50")
    assert Decimal(data["fee_rate"]) == Decimal("0.0005")


@pytest.mark.anyio
async def test_create_order_response_has_exchange_order_id(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """주문 응답에 거래소 주문 ID 포함 확인."""
    expected = _make_order_response(exchange_order_id="upbit-abc123")
    mock_order_service.create_order.return_value = expected

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["exchange_order_id"] == "upbit-abc123"


@pytest.mark.anyio
async def test_create_market_buy_without_amount_returns_422(client: AsyncClient):
    """시장가 매수 시 amount 없음 → 422 (Pydantic model_validator)."""
    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            # amount 누락
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_market_sell_without_quantity_returns_422(client: AsyncClient):
    """시장가 매도 시 quantity 없음 → 422 (Pydantic model_validator)."""
    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "sell",
            "method": "market",
            # quantity 누락
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_limit_order_without_price_returns_422(client: AsyncClient):
    """지정가 주문 시 price 없음 → 422."""
    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "limit",
            "quantity": "0.001",
            # price 누락
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_limit_order_without_quantity_returns_422(client: AsyncClient):
    """지정가 주문 시 quantity 없음 → 422."""
    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "limit",
            "price": "95000000",
            # quantity 누락
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_order_negative_amount_returns_422(client: AsyncClient):
    """음수 amount → 422 (model_validator: amount must be positive)."""
    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "-1000",
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_order_zero_price_returns_422(client: AsyncClient):
    """지정가 주문 시 price=0 → 422 (price must be positive)."""
    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "limit",
            "price": "0",
            "quantity": "0.001",
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_order_invalid_side_returns_422(client: AsyncClient):
    """잘못된 side 값 → 422."""
    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "long",
            "method": "market",
            "amount": "100000",
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_order_invalid_method_returns_422(client: AsyncClient):
    """잘못된 method 값 → 422."""
    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "stop_limit",
            "amount": "100000",
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_order_exchange_account_not_found_returns_404(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """거래소 계정 미존재 또는 타인 소유 → 404 EXCHANGE_ACCOUNT_NOT_FOUND."""
    mock_order_service.create_order.side_effect = ExchangeErrors.account_not_found()

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "EXCHANGE_ACCOUNT_NOT_FOUND"


@pytest.mark.anyio
async def test_create_order_coin_not_found_returns_404(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """코인 미존재 → 404 COIN_NOT_FOUND."""
    mock_order_service.create_order.side_effect = CoinErrors.not_found()

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "COIN_NOT_FOUND"


@pytest.mark.anyio
async def test_create_order_insufficient_balance_returns_422(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """잔고 부족 → 422 INSUFFICIENT_BALANCE."""
    mock_order_service.create_order.side_effect = OrderErrors.insufficient_balance()

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "999999999",
        },
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INSUFFICIENT_BALANCE"


@pytest.mark.anyio
async def test_create_order_exchange_unavailable_returns_503(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """거래소 연결 불가 → 503 EXCHANGE_UNAVAILABLE."""
    mock_order_service.create_order.side_effect = OrderErrors.exchange_unavailable()

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "EXCHANGE_UNAVAILABLE"


@pytest.mark.anyio
async def test_create_order_exchange_order_failed_returns_502(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """거래소 주문 처리 실패 → 502 EXCHANGE_ORDER_FAILED."""
    mock_order_service.create_order.side_effect = OrderErrors.exchange_order_failed(
        "최소 주문 금액 미달"
    )

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "EXCHANGE_ORDER_FAILED"


@pytest.mark.anyio
async def test_create_order_circuit_open_returns_503(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """Circuit Breaker OPEN → 503 EXCHANGE_CIRCUIT_OPEN."""
    mock_order_service.create_order.side_effect = ExchangeErrors.circuit_open("upbit")

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "EXCHANGE_CIRCUIT_OPEN"


@pytest.mark.anyio
async def test_create_order_rate_limited_returns_429(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """거래소 Rate Limit 초과 → 429 EXCHANGE_RATE_LIMITED."""
    mock_order_service.create_order.side_effect = ExchangeErrors.rate_limited(
        "upbit", retry_after_seconds=60
    )

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "EXCHANGE_RATE_LIMITED"


# ── GET /orders — 주문 목록 ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_orders_returns_200_with_paginated_items(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """주문 목록 조회 → 200 + items + 페이지네이션 정보."""
    orders = [_make_order_response(), _make_order_response()]
    expected = _make_paginated_orders(items=orders, total=2)
    mock_order_service.list_orders.return_value = expected

    resp = await client.get("/orders")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 2
    assert data["total"] == 2
    assert data["page"] == 1
    assert "pages" in data
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_list_orders_empty_returns_empty_list(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """주문 없을 때 → 200 + 빈 배열."""
    mock_order_service.list_orders.return_value = _make_paginated_orders(total=0)

    resp = await client.get("/orders")

    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []
    assert resp.json()["data"]["total"] == 0


@pytest.mark.anyio
async def test_list_orders_filter_by_status(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """status=filled 필터 → 200 (서비스 호출 확인)."""
    mock_order_service.list_orders.return_value = _make_paginated_orders()

    resp = await client.get("/orders", params={"status": "filled"})

    assert resp.status_code == 200
    mock_order_service.list_orders.assert_called_once()


@pytest.mark.anyio
async def test_list_orders_filter_by_side(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """side=buy 필터 → 200."""
    mock_order_service.list_orders.return_value = _make_paginated_orders()

    resp = await client.get("/orders", params={"side": "buy"})

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_list_orders_filter_by_exchange_account_id(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """exchange_account_id 필터 → 200."""
    mock_order_service.list_orders.return_value = _make_paginated_orders()

    resp = await client.get(
        "/orders", params={"exchange_account_id": str(uuid.uuid4())}
    )

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_list_orders_filter_by_coin_id(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """coin_id 필터 → 200."""
    mock_order_service.list_orders.return_value = _make_paginated_orders()

    resp = await client.get("/orders", params={"coin_id": str(uuid.uuid4())})

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_list_orders_pagination_params(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """page=2, size=5 페이지네이션 → 200 + 응답 페이지 정보 일치."""
    orders = [_make_order_response() for _ in range(5)]
    expected = _make_paginated_orders(items=orders, total=50, page=2, size=5)
    mock_order_service.list_orders.return_value = expected

    resp = await client.get("/orders", params={"page": 2, "size": 5})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["page"] == 2
    assert data["size"] == 5
    assert data["total"] == 50
    assert data["pages"] == 10


@pytest.mark.anyio
async def test_list_orders_date_range_filter(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """from_dt / to_dt 기간 필터 → 200."""
    mock_order_service.list_orders.return_value = _make_paginated_orders()

    resp = await client.get(
        "/orders",
        params={
            "from_dt": "2026-01-01T00:00:00Z",
            "to_dt": "2026-03-14T23:59:59Z",
        },
    )

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_list_orders_invalid_status_returns_422(client: AsyncClient):
    """잘못된 status 값 → 422 (Enum 검증 실패)."""
    resp = await client.get("/orders", params={"status": "invalid_status"})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_list_orders_invalid_side_returns_422(client: AsyncClient):
    """잘못된 side 값 → 422."""
    resp = await client.get("/orders", params={"side": "long"})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_list_orders_page_zero_returns_422(client: AsyncClient):
    """page=0 → 422 (ge=1 제약)."""
    resp = await client.get("/orders", params={"page": 0})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_list_orders_size_over_100_returns_422(client: AsyncClient):
    """size > 100 → 422 (le=100 제약)."""
    resp = await client.get("/orders", params={"size": 101})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_list_orders_response_items_have_required_fields(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """목록 아이템에 필수 필드 포함 확인."""
    orders = [_make_order_response()]
    mock_order_service.list_orders.return_value = _make_paginated_orders(
        items=orders, total=1
    )

    resp = await client.get("/orders")

    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    required_fields = [
        "id",
        "coin_symbol",
        "exchange_type",
        "side",
        "method",
        "status",
        "fee",
        "is_ai_order",
        "created_at",
    ]
    for field in required_fields:
        assert field in item, f"필드 누락: {field}"


# ── GET /orders/{order_id} — 주문 상세 ───────────────────────────────────────


@pytest.mark.anyio
async def test_get_order_returns_200_with_full_response(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """주문 상세 조회 → 200 + 전체 필드 포함."""
    order_id = uuid.uuid4()
    expected = _make_order_response(
        status="filled",
        exchange_order_id="upbit-abc123",
        is_ai_order=False,
    )
    mock_order_service.get_order.return_value = expected

    resp = await client.get(f"/orders/{order_id}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "filled"
    assert data["exchange_order_id"] == "upbit-abc123"
    assert data["is_ai_order"] is False
    assert "coin_symbol" in data
    assert "exchange_type" in data
    assert "executed_quantity" in data
    assert "executed_price" in data
    assert "fee" in data
    assert "fee_rate" in data
    assert "fee_currency" in data
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_get_order_open_status_returns_200(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """OPEN 상태 주문 상세 조회 → 200 + executed_at=None."""
    expected = _make_order_response(method="limit", status="open")
    expected.executed_at = None
    mock_order_service.get_order.return_value = expected

    resp = await client.get(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "open"
    assert data["executed_at"] is None


@pytest.mark.anyio
async def test_get_order_partial_status_returns_200(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """PARTIAL 상태 주문 조회 → 200."""
    expected = _make_order_response(
        method="limit",
        status="partial",
        executed_quantity=Decimal("0.0005"),
    )
    mock_order_service.get_order.return_value = expected

    resp = await client.get(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "partial"
    assert Decimal(data["executed_quantity"]) == Decimal("0.0005")


@pytest.mark.anyio
async def test_get_order_not_found_returns_404(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """존재하지 않는 주문 조회 → 404 ORDER_NOT_FOUND."""
    mock_order_service.get_order.side_effect = OrderErrors.not_found()

    resp = await client.get(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ORDER_NOT_FOUND"


@pytest.mark.anyio
async def test_get_order_other_user_returns_404_not_403(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """타인 주문 조회 → 404 (정보 노출 방지 — 403 아닌 404 반환)."""
    mock_order_service.get_order.side_effect = OrderErrors.not_found()

    resp = await client.get(f"/orders/{uuid.uuid4()}")

    # 403이 아닌 404 반환으로 주문 존재 여부 노출 방지
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ORDER_NOT_FOUND"


# ── DELETE /orders/{order_id} — 주문 취소 ────────────────────────────────────


@pytest.mark.anyio
async def test_cancel_pending_order_returns_200_with_cancelled_status(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """PENDING 주문 취소 → 200 + status=cancelled."""
    expected = _make_order_response(status="cancelled")
    mock_order_service.cancel_order.return_value = expected

    resp = await client.delete(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "cancelled"
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_cancel_open_order_returns_200_with_cancelled_status(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """OPEN 지정가 주문 취소 → 200 + status=cancelled."""
    expected = _make_order_response(status="cancelled", method="limit")
    mock_order_service.cancel_order.return_value = expected

    resp = await client.delete(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"


@pytest.mark.anyio
async def test_cancel_partial_order_preserves_executed_info(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """PARTIAL 주문 취소 → 200 + 부분 체결 수량/수수료 보존."""
    expected = _make_order_response(
        status="cancelled",
        executed_quantity=Decimal("0.0005"),
        fee=Decimal("25"),
        fee_currency="KRW",
    )
    mock_order_service.cancel_order.return_value = expected

    resp = await client.delete(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "cancelled"
    assert Decimal(data["executed_quantity"]) == Decimal("0.0005")
    assert Decimal(data["fee"]) == Decimal("25")


@pytest.mark.anyio
async def test_cancel_filled_order_returns_422(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """체결 완료 주문 취소 시도 → 422 ORDER_CANNOT_CANCEL."""
    mock_order_service.cancel_order.side_effect = OrderErrors.cannot_cancel("filled")

    resp = await client.delete(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "ORDER_CANNOT_CANCEL"


@pytest.mark.anyio
async def test_cancel_failed_order_returns_422(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """FAILED 주문 취소 시도 → 422 ORDER_CANNOT_CANCEL."""
    mock_order_service.cancel_order.side_effect = OrderErrors.cannot_cancel("failed")

    resp = await client.delete(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "ORDER_CANNOT_CANCEL"


@pytest.mark.anyio
async def test_cancel_order_not_found_returns_404(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """존재하지 않는 주문 취소 → 404 ORDER_NOT_FOUND."""
    mock_order_service.cancel_order.side_effect = OrderErrors.not_found()

    resp = await client.delete(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ORDER_NOT_FOUND"


@pytest.mark.anyio
async def test_cancel_order_exchange_unavailable_returns_503(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """취소 중 거래소 연결 불가 → 503 EXCHANGE_UNAVAILABLE."""
    mock_order_service.cancel_order.side_effect = OrderErrors.exchange_unavailable()

    resp = await client.delete(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "EXCHANGE_UNAVAILABLE"


@pytest.mark.anyio
async def test_cancel_order_already_filled_syncs_to_filled(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """취소 시도 시 이미 체결 → 서비스가 status=filled로 동기화 후 응답."""
    # 서비스가 filled 상태 응답을 반환 (취소 불가 에러 아닌 정상 응답)
    expected = _make_order_response(status="filled")
    mock_order_service.cancel_order.return_value = expected

    resp = await client.delete(f"/orders/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "filled"


# ── POST /orders/batch-cancel — 일괄 취소 ────────────────────────────────────


@pytest.mark.anyio
async def test_batch_cancel_all_success_returns_200(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """전체 취소 성공 → 200 + success_count=3, failed_count=0."""
    order_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    expected = _make_batch_cancel_response(success_ids=order_ids)
    mock_order_service.batch_cancel.return_value = expected

    resp = await client.post(
        "/orders/batch-cancel",
        json={"order_ids": [str(oid) for oid in order_ids]},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["success_count"] == 3
    assert data["failed_count"] == 0
    assert len(data["success_ids"]) == 3
    assert data["failed"] == []
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_batch_cancel_partial_success_returns_200(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """부분 성공 — 일부 취소 실패 → 200 + failed 목록 포함."""
    success_id = uuid.uuid4()
    fail_id = uuid.uuid4()
    expected = _make_batch_cancel_response(
        success_ids=[success_id],
        failed=[BatchCancelFailure(order_id=fail_id, reason="취소 불가 상태: filled")],
    )
    mock_order_service.batch_cancel.return_value = expected

    resp = await client.post(
        "/orders/batch-cancel",
        json={"order_ids": [str(success_id), str(fail_id)]},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["success_count"] == 1
    assert data["failed_count"] == 1
    assert len(data["failed"]) == 1
    assert data["failed"][0]["reason"] == "취소 불가 상태: filled"


@pytest.mark.anyio
async def test_batch_cancel_all_failed_returns_200(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """모두 실패 → 200 (부분 성공 허용 정책 — HTTP 에러 아님)."""
    fail_id = uuid.uuid4()
    expected = _make_batch_cancel_response(
        failed=[BatchCancelFailure(order_id=fail_id, reason="주문을 찾을 수 없습니다.")]
    )
    mock_order_service.batch_cancel.return_value = expected

    resp = await client.post(
        "/orders/batch-cancel",
        json={"order_ids": [str(fail_id)]},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["success_count"] == 0
    assert data["failed_count"] == 1


@pytest.mark.anyio
async def test_batch_cancel_order_not_owned_in_failed_list(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """타인 주문 포함 시 → failed 목록에 포함."""
    own_id = uuid.uuid4()
    other_id = uuid.uuid4()
    expected = _make_batch_cancel_response(
        success_ids=[own_id],
        failed=[BatchCancelFailure(order_id=other_id, reason="주문을 찾을 수 없습니다.")],
    )
    mock_order_service.batch_cancel.return_value = expected

    resp = await client.post(
        "/orders/batch-cancel",
        json={"order_ids": [str(own_id), str(other_id)]},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["success_count"] == 1
    assert data["failed_count"] == 1


@pytest.mark.anyio
async def test_batch_cancel_empty_order_ids_returns_422(client: AsyncClient):
    """빈 order_ids → 422 (min_length=1 제약)."""
    resp = await client.post(
        "/orders/batch-cancel",
        json={"order_ids": []},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_batch_cancel_over_max_order_ids_returns_422(client: AsyncClient):
    """order_ids 21개 → 422 (max_length=20 제약)."""
    resp = await client.post(
        "/orders/batch-cancel",
        json={"order_ids": [str(uuid.uuid4()) for _ in range(21)]},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_batch_cancel_missing_order_ids_field_returns_422(client: AsyncClient):
    """order_ids 필드 누락 → 422."""
    resp = await client.post("/orders/batch-cancel", json={})
    assert resp.status_code == 422


# ── 주문 상태 전이 시나리오 ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_market_buy_order_results_in_filled_status(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """시장가 매수 → 즉시 체결 → status=filled."""
    expected = _make_order_response(method="market", side="buy", status="filled")
    mock_order_service.create_order.return_value = expected

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "filled"


@pytest.mark.anyio
async def test_limit_order_results_in_open_status(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """지정가 주문 → 거래소 접수 → status=open (체결 대기)."""
    expected = _make_order_response(method="limit", side="buy", status="open")
    mock_order_service.create_order.return_value = expected

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "limit",
            "price": "95000000",
            "quantity": "0.001",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "open"


@pytest.mark.anyio
async def test_failed_order_status_is_failed(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """거래소 거부 → 서비스에서 FAILED 상태로 전이 → OrderErrors 발생."""
    mock_order_service.create_order.side_effect = OrderErrors.exchange_order_failed(
        "거래소 점검 중"
    )

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    # 서비스에서 FAILED 전이 후 에러 raise → 클라이언트에 502 반환
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "EXCHANGE_ORDER_FAILED"


# ── 응답 포맷 공통 검증 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_successful_response_has_meta_timestamp(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """성공 응답에 meta.timestamp 포함."""
    mock_order_service.list_orders.return_value = _make_paginated_orders()

    resp = await client.get("/orders")

    body = resp.json()
    assert "meta" in body
    assert "timestamp" in body["meta"]


@pytest.mark.anyio
async def test_error_response_has_code_and_message_fields(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """에러 응답 포맷 — code, message 필드 존재."""
    mock_order_service.create_order.side_effect = AppError("TEST_CODE", "테스트", 400)

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    error = resp.json()["error"]
    assert "code" in error
    assert "message" in error


@pytest.mark.anyio
async def test_create_order_response_no_sensitive_fields(
    client: AsyncClient, mock_order_service: AsyncMock
):
    """주문 응답에 API 키 등 민감 정보 미포함."""
    expected = _make_order_response()
    mock_order_service.create_order.return_value = expected

    resp = await client.post(
        "/orders",
        json={
            "exchange_account_id": str(uuid.uuid4()),
            "coin_id": str(uuid.uuid4()),
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert "api_secret" not in data
    assert "api_key" not in data
    assert "password" not in data
