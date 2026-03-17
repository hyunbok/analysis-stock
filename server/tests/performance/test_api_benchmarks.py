"""API 응답 시간 벤치마크 — pytest-benchmark.

성능 기준 (설계서 ST6):
  - API 응답 (코인 목록): < 200ms (mean)
  - API 응답 (주문 목록): < 300ms (mean, mock 기준)

구현 방식:
  - ASGI transport + 의존성 오버라이드로 외부 DB/Redis I/O 제거
  - benchmark()는 동기 함수만 직접 지원하므로 asyncio.run() 래핑 사용
  - 측정값에는 asyncio.run() 이벤트 루프 생성 오버헤드(~수십 μs)가 포함됨
    실제 프로덕션 응답 시간보다 약간 높게 측정될 수 있으며, 절대값보다
    회귀(regression) 감지 목적으로 활용할 것을 권장
  - 실제 네트워크/DB 레이턴시 포함 측정은 locustfile.py (스테이징 환경) 사용
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers

pytestmark = pytest.mark.benchmark


def _assert_perf(benchmark, threshold_sec: float, label: str) -> None:
    if benchmark.stats:
        assert benchmark.stats["mean"] < threshold_sec, (
            f"{label}: {benchmark.stats['mean'] * 1000:.1f}ms > {threshold_sec * 1000:.0f}ms"
        )


# ── coins 앱 픽스처 ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def coins_app() -> FastAPI:
    """코인 검색 API 전용 테스트 앱."""
    from app.api.v1.coins import router as coins_router
    from app.core.deps import get_coin_service, get_current_user_optional
    from app.schemas.coin import CoinResponse, PaginatedCoins

    mock_svc = AsyncMock()

    def _make_paginated(n: int = 20) -> PaginatedCoins:
        items = [
            CoinResponse(
                id=uuid.uuid4(),
                symbol=f"COIN{i:03d}",
                name_ko=f"코인{i}",
                name_en=f"Coin{i}",
                exchange_type="upbit",
                market_code=f"KRW-COIN{i:03d}",
                is_active=True,
                current_price=Decimal("50000000"),
            )
            for i in range(n)
        ]
        return PaginatedCoins.build(items=items, total=100, page=1, size=n)

    mock_svc.search_coins.return_value = _make_paginated(20)

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(coins_router, prefix="/coins")
    app.dependency_overrides[get_coin_service] = lambda: mock_svc
    app.dependency_overrides[get_current_user_optional] = lambda: None
    return app


# ── orders 앱 픽스처 ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def orders_mock_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "bench@example.com"
    user.nickname = "bench_user"
    user.avatar_url = None
    user.language = "ko"
    user.theme = "system"
    user.price_color_style = "korean"
    user.ai_trading_enabled = False
    user.is_2fa_enabled = False
    user.email_verified_at = datetime.now(UTC)
    user.soft_deleted_at = None
    user.created_at = datetime.now(UTC)
    return user


@pytest.fixture(scope="module")
def orders_app(orders_mock_user: MagicMock) -> FastAPI:
    """주문 목록 API 전용 테스트 앱."""
    from app.api.v1.orders import router as orders_router
    from app.core.deps import get_current_user, get_order_service
    from app.providers.enums import ExchangeType, OrderMethod, OrderSide, OrderStatus
    from app.schemas.order import OrderResponse, PaginatedOrders

    mock_svc = AsyncMock()

    def _make_paginated_orders(n: int = 20) -> PaginatedOrders:
        items = [
            OrderResponse(
                id=uuid.uuid4(),
                exchange_account_id=uuid.uuid4(),
                coin_id=uuid.uuid4(),
                coin_symbol="BTC",
                exchange_type=ExchangeType.UPBIT,
                side=OrderSide.BUY,
                method=OrderMethod.LIMIT,
                status=OrderStatus.FILLED,
                price=Decimal("50000000"),
                quantity=Decimal("0.001"),
                amount=None,
                executed_quantity=Decimal("0.001"),
                executed_price=Decimal("50000000"),
                fee=Decimal("50"),
                fee_rate=Decimal("0.0005"),
                fee_currency="KRW",
                exchange_order_id=f"ord_{i}",
                is_ai_order=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                executed_at=datetime.now(UTC),
            )
            for i in range(n)
        ]
        return PaginatedOrders.build(items=items, total=100, page=1, size=n)

    mock_svc.list_orders.return_value = _make_paginated_orders(20)

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(orders_router, prefix="/orders")
    app.dependency_overrides[get_current_user] = lambda: orders_mock_user
    app.dependency_overrides[get_order_service] = lambda: mock_svc
    return app


# ── 벤치마크: coins ───────────────────────────────────────────────────────────

class TestCoinListBenchmark:
    """코인 목록 API 응답 시간 — 기준: < 200ms."""

    def test_search_coins_p95(self, benchmark, coins_app: FastAPI):
        """GET /coins 응답 시간 측정.

        mock 서비스 주입으로 DB 레이턴시 제거.
        기준: mean < 200ms.
        """
        async def _call_coro():
            async with AsyncClient(
                transport=ASGITransport(app=coins_app), base_url="http://test"
            ) as client:
                resp = await client.get("/coins?page=1&size=20")
                assert resp.status_code == 200
                body = resp.json()
                assert body["error"] is None
                assert body["data"]["total"] == 100

        def _call():
            asyncio.run(_call_coro())

        benchmark(_call)
        _assert_perf(benchmark, 0.200, "GET /coins 응답")

    def test_search_coins_with_query(self, benchmark, coins_app: FastAPI):
        """검색 파라미터 포함 GET /coins?q=BTC 응답 시간."""
        async def _call_coro():
            async with AsyncClient(
                transport=ASGITransport(app=coins_app), base_url="http://test"
            ) as client:
                resp = await client.get("/coins?q=BTC&page=1&size=20")
                assert resp.status_code == 200

        def _call():
            asyncio.run(_call_coro())

        benchmark(_call)
        _assert_perf(benchmark, 0.200, "GET /coins?q=BTC 응답")


# ── 벤치마크: orders ─────────────────────────────────────────────────────────

class TestOrderListBenchmark:
    """주문 목록 API 응답 시간 — 기준: < 300ms."""

    def test_list_orders(self, benchmark, orders_app: FastAPI):
        """GET /orders 응답 시간 측정.

        인증 mock 주입으로 JWT 검증 오버헤드 제거.
        기준: mean < 300ms.
        """
        async def _call_coro():
            async with AsyncClient(
                transport=ASGITransport(app=orders_app), base_url="http://test"
            ) as client:
                resp = await client.get("/orders?page=1&size=20")
                assert resp.status_code == 200
                body = resp.json()
                assert body["error"] is None

        def _call():
            asyncio.run(_call_coro())

        benchmark(_call)
        _assert_perf(benchmark, 0.300, "GET /orders 응답")
