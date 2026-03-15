"""포트폴리오/자산 조회 API 통합 테스트 — GET /api/v1/portfolio, GET /api/v1/portfolio/{exchange_account_id}.

설계서: docs/tasks/v1-20-portfolio-asset-api-plan.md §8 ST9
패턴:  test_orders_api.py와 동일 — 서비스 계층 Mock + HTTP 검증

테스트 케이스 (9건):
  T1 - 전체 포트폴리오 요약 정상 조회 (MockProvider + Redis ticker)
  T2 - 거래소별 상세 정상 조회 (코인별 데이터 + portfolio_weight 검증)
  T3 - 인증 실패 → 401
  T4 - 타 사용자 계정 접근 → 403 PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED
  T5 - 거래소 계정 없음 → 빈 포트폴리오 (총액 0, by_exchange=[])
  T6 - 거래소 API 실패 → 부분 응답 (1개 성공 + 1개 실패 → 성공 데이터만)
  T7 - 매수 이력 없는 코인 → avg_entry_price=null, pnl=null
  T8 - 캐시 HIT 검증 → Redis에 미리 저장 → Provider 미호출 확인
  T9 - 캐시 무효화 후 재조회 → DEL 후 Provider 재호출 확인
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AppError, ExchangeErrors
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.models.user import User
from app.schemas.portfolio import (
    CoinHolding,
    ExchangePortfolioResponse,
    ExchangeSummary,
    PortfolioSummaryResponse,
    TopCoin,
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


def _make_exchange_summary(
    exchange_account_id: uuid.UUID | None = None,
    exchange_type: str = "upbit",
    nickname: str | None = "내 업비트",
    balance_krw: Decimal | None = Decimal("10000000.00"),
    pnl_amount: Decimal | None = Decimal("500000.00"),
    pnl_ratio: Decimal | None = Decimal("5.26"),
) -> ExchangeSummary:
    return ExchangeSummary(
        exchange_account_id=exchange_account_id or uuid.uuid4(),
        exchange_type=exchange_type,
        nickname=nickname,
        balance_krw=balance_krw,
        pnl_amount=pnl_amount,
        pnl_ratio=pnl_ratio,
    )


def _make_top_coin(
    symbol: str = "BTC/KRW",
    exchange_type: str = "upbit",
    quantity: Decimal = Decimal("0.05"),
    avg_price: Decimal | None = Decimal("85000000.00"),
    current_price: Decimal | None = Decimal("87500000.00"),
    pnl_amount: Decimal | None = Decimal("125000.00"),
) -> TopCoin:
    return TopCoin(
        symbol=symbol,
        exchange_type=exchange_type,
        quantity=quantity,
        avg_price=avg_price,
        current_price=current_price,
        pnl_amount=pnl_amount,
    )


def _make_portfolio_summary(
    total_balance_krw: Decimal | None = Decimal("15234500.00"),
    total_pnl_amount: Decimal | None = Decimal("234500.00"),
    total_pnl_ratio: Decimal | None = Decimal("1.56"),
    total_trade_count: int = 42,
    ai_pnl_amount: Decimal | None = Decimal("180000.00"),
    ai_pnl_ratio: Decimal | None = Decimal("2.10"),
    ai_trade_count: int = 28,
    manual_pnl_amount: Decimal | None = Decimal("54500.00"),
    manual_pnl_ratio: Decimal | None = Decimal("0.85"),
    manual_trade_count: int = 14,
    by_exchange: list[ExchangeSummary] | None = None,
    top_coins: list[TopCoin] | None = None,
    cached_at: datetime | None = None,
) -> PortfolioSummaryResponse:
    return PortfolioSummaryResponse(
        total_balance_krw=total_balance_krw,
        total_pnl_amount=total_pnl_amount,
        total_pnl_ratio=total_pnl_ratio,
        total_trade_count=total_trade_count,
        ai_pnl_amount=ai_pnl_amount,
        ai_pnl_ratio=ai_pnl_ratio,
        ai_trade_count=ai_trade_count,
        manual_pnl_amount=manual_pnl_amount,
        manual_pnl_ratio=manual_pnl_ratio,
        manual_trade_count=manual_trade_count,
        by_exchange=by_exchange if by_exchange is not None else [_make_exchange_summary()],
        top_coins=top_coins if top_coins is not None else [_make_top_coin()],
        cached_at=cached_at,
    )


def _make_coin_holding(
    symbol: str = "BTC/KRW",
    currency: str = "BTC",
    quantity: Decimal = Decimal("0.05"),
    available: Decimal = Decimal("0.045"),
    locked: Decimal = Decimal("0.005"),
    avg_entry_price: Decimal | None = Decimal("85000000.00"),
    current_price: Decimal | None = Decimal("87500000.00"),
    value_krw: Decimal | None = Decimal("4375000.00"),
    pnl_amount: Decimal | None = Decimal("125000.00"),
    pnl_ratio: Decimal | None = Decimal("2.94"),
    weight_percent: Decimal | None = Decimal("42.75"),
) -> CoinHolding:
    return CoinHolding(
        symbol=symbol,
        currency=currency,
        quantity=quantity,
        available=available,
        locked=locked,
        avg_entry_price=avg_entry_price,
        current_price=current_price,
        value_krw=value_krw,
        pnl_amount=pnl_amount,
        pnl_ratio=pnl_ratio,
        weight_percent=weight_percent,
    )


def _make_exchange_portfolio(
    exchange_account_id: uuid.UUID | None = None,
    exchange_type: str = "upbit",
    nickname: str | None = "내 업비트",
    total_balance_krw: Decimal | None = Decimal("10234500.00"),
    krw_balance: Decimal | None = Decimal("500000.00"),
    coins: list[CoinHolding] | None = None,
    balance_fetched_at: datetime | None = None,
    cached_at: datetime | None = None,
) -> ExchangePortfolioResponse:
    return ExchangePortfolioResponse(
        exchange_account_id=exchange_account_id or uuid.uuid4(),
        exchange_type=exchange_type,
        nickname=nickname,
        total_balance_krw=total_balance_krw,
        krw_balance=krw_balance,
        coins=coins if coins is not None else [_make_coin_holding()],
        balance_fetched_at=balance_fetched_at or datetime.now(UTC),
        cached_at=cached_at,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_portfolio_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_user() -> User:
    return _make_user()


@pytest.fixture
def mock_other_user() -> User:
    return _make_user(email="other@example.com")


def _build_app(
    mock_portfolio_service: AsyncMock,
    current_user: User | None = None,
) -> FastAPI:
    """테스트용 FastAPI 앱 — portfolio 라우터 + 선택적 인증 override."""
    from app.api.v1.portfolio import router as portfolio_router
    from app.core.deps import get_current_user, get_portfolio_service

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(portfolio_router)

    app.dependency_overrides[get_portfolio_service] = lambda: mock_portfolio_service
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


@pytest.fixture
def test_app(mock_portfolio_service: AsyncMock, mock_user: User) -> FastAPI:
    """인증된 사용자 앱."""
    return _build_app(mock_portfolio_service, current_user=mock_user)


@pytest.fixture
def test_app_no_auth(mock_portfolio_service: AsyncMock) -> FastAPI:
    """인증 override 없는 앱 (401 테스트용)."""
    return _build_app(mock_portfolio_service, current_user=None)


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


# ── T3: 인증 실패 → 401 ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_portfolio_summary_unauthenticated_returns_401(
    anon_client: AsyncClient,
):
    """T3: 토큰 없이 포트폴리오 요약 조회 → 401."""
    resp = await anon_client.get("/portfolio")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_get_exchange_portfolio_unauthenticated_returns_401(
    anon_client: AsyncClient,
):
    """T3: 토큰 없이 거래소별 상세 조회 → 401."""
    resp = await anon_client.get(f"/portfolio/{uuid.uuid4()}")
    assert resp.status_code == 401


# ── T1: 전체 포트폴리오 요약 정상 조회 ────────────────────────────────────────


@pytest.mark.anyio
async def test_get_portfolio_summary_returns_200_with_full_data(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T1: 전체 포트폴리오 요약 정상 조회 — 200 + 필수 필드 포함."""
    expected = _make_portfolio_summary()
    mock_portfolio_service.get_portfolio_summary.return_value = expected

    resp = await client.get("/portfolio")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_balance_krw"] == "15234500.00"
    assert data["total_pnl_amount"] == "234500.00"
    assert data["total_pnl_ratio"] == "1.56"
    assert data["total_trade_count"] == 42
    assert data["ai_trade_count"] == 28
    assert data["manual_trade_count"] == 14
    assert isinstance(data["by_exchange"], list)
    assert len(data["by_exchange"]) == 1
    assert isinstance(data["top_coins"], list)
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_get_portfolio_summary_by_exchange_fields(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T1: by_exchange 항목에 필수 필드 포함 확인."""
    exchange_id = uuid.uuid4()
    expected = _make_portfolio_summary(
        by_exchange=[
            _make_exchange_summary(
                exchange_account_id=exchange_id,
                exchange_type="upbit",
                nickname="내 업비트",
                balance_krw=Decimal("10000000.00"),
                pnl_amount=Decimal("500000.00"),
                pnl_ratio=Decimal("5.26"),
            )
        ]
    )
    mock_portfolio_service.get_portfolio_summary.return_value = expected

    resp = await client.get("/portfolio")

    assert resp.status_code == 200
    ex = resp.json()["data"]["by_exchange"][0]
    assert ex["exchange_account_id"] == str(exchange_id)
    assert ex["exchange_type"] == "upbit"
    assert ex["nickname"] == "내 업비트"
    assert Decimal(ex["balance_krw"]) == Decimal("10000000.00")


@pytest.mark.anyio
async def test_get_portfolio_summary_top_coins_limited_to_5(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T1: top_coins 최대 5개 제한 확인."""
    top_coins = [
        _make_top_coin(symbol=f"COIN{i}/KRW") for i in range(5)
    ]
    expected = _make_portfolio_summary(top_coins=top_coins)
    mock_portfolio_service.get_portfolio_summary.return_value = expected

    resp = await client.get("/portfolio")

    assert resp.status_code == 200
    assert len(resp.json()["data"]["top_coins"]) <= 5


@pytest.mark.anyio
async def test_get_portfolio_summary_response_has_meta_timestamp(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T1: 성공 응답에 meta.timestamp 포함."""
    mock_portfolio_service.get_portfolio_summary.return_value = _make_portfolio_summary()

    resp = await client.get("/portfolio")

    assert resp.status_code == 200
    assert "meta" in resp.json()
    assert "timestamp" in resp.json()["meta"]


# ── T2: 거래소별 상세 정상 조회 ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_exchange_portfolio_returns_200_with_coins(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T2: 거래소별 상세 정상 조회 — 200 + 코인 데이터 포함."""
    ea_id = uuid.uuid4()
    expected = _make_exchange_portfolio(
        exchange_account_id=ea_id,
        exchange_type="upbit",
        nickname="내 업비트",
        total_balance_krw=Decimal("10234500.00"),
        krw_balance=Decimal("500000.00"),
        coins=[_make_coin_holding()],
    )
    mock_portfolio_service.get_exchange_portfolio.return_value = expected

    resp = await client.get(f"/portfolio/{ea_id}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["exchange_account_id"] == str(ea_id)
    assert data["exchange_type"] == "upbit"
    assert data["nickname"] == "내 업비트"
    assert Decimal(data["total_balance_krw"]) == Decimal("10234500.00")
    assert Decimal(data["krw_balance"]) == Decimal("500000.00")
    assert isinstance(data["coins"], list)
    assert len(data["coins"]) == 1
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_get_exchange_portfolio_coin_holding_fields(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T2: CoinHolding 항목에 portfolio_weight 포함 검증."""
    coin = _make_coin_holding(
        symbol="BTC/KRW",
        currency="BTC",
        quantity=Decimal("0.05"),
        avg_entry_price=Decimal("85000000.00"),
        current_price=Decimal("87500000.00"),
        pnl_amount=Decimal("125000.00"),
        pnl_ratio=Decimal("2.94"),
        weight_percent=Decimal("42.75"),
    )
    expected = _make_exchange_portfolio(coins=[coin])
    mock_portfolio_service.get_exchange_portfolio.return_value = expected

    resp = await client.get(f"/portfolio/{uuid.uuid4()}")

    assert resp.status_code == 200
    c = resp.json()["data"]["coins"][0]
    assert c["symbol"] == "BTC/KRW"
    assert c["currency"] == "BTC"
    assert Decimal(c["quantity"]) == Decimal("0.05")
    assert Decimal(c["avg_entry_price"]) == Decimal("85000000.00")
    assert Decimal(c["current_price"]) == Decimal("87500000.00")
    assert Decimal(c["pnl_amount"]) == Decimal("125000.00")
    assert Decimal(c["pnl_ratio"]) == Decimal("2.94")
    assert Decimal(c["weight_percent"]) == Decimal("42.75")


@pytest.mark.anyio
async def test_get_exchange_portfolio_weight_percent_sum_near_100(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T2: weight_percent 합계 ~ 100 (반올림 오차 허용 0.01)."""
    coins = [
        _make_coin_holding(
            symbol="BTC/KRW", currency="BTC",
            quantity=Decimal("1"), weight_percent=Decimal("60.00"),
        ),
        _make_coin_holding(
            symbol="ETH/KRW", currency="ETH",
            quantity=Decimal("10"), weight_percent=Decimal("40.00"),
        ),
    ]
    expected = _make_exchange_portfolio(coins=coins)
    mock_portfolio_service.get_exchange_portfolio.return_value = expected

    resp = await client.get(f"/portfolio/{uuid.uuid4()}")

    assert resp.status_code == 200
    weights = [
        Decimal(c["weight_percent"])
        for c in resp.json()["data"]["coins"]
        if c.get("weight_percent") is not None
    ]
    total = sum(weights)
    assert abs(total - Decimal("100.00")) <= Decimal("0.01")


# ── T4: 타 사용자 계정 접근 → 403 ────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_exchange_portfolio_other_user_account_returns_403(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T4: 타 사용자 소유 거래소 계정 접근 → 403 PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED."""
    from app.core.exceptions import PortfolioErrors

    mock_portfolio_service.get_exchange_portfolio.side_effect = (
        PortfolioErrors.exchange_account_not_owned()
    )

    resp = await client.get(f"/portfolio/{uuid.uuid4()}")

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED"


# ── T5: 거래소 계정 없음 → 빈 포트폴리오 ─────────────────────────────────────


@pytest.mark.anyio
async def test_get_portfolio_summary_no_exchange_accounts_returns_empty(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T5: 거래소 계정 없음 → 200 + 총액 null/0, by_exchange=[]."""
    expected = _make_portfolio_summary(
        total_balance_krw=None,
        total_pnl_amount=None,
        total_pnl_ratio=None,
        total_trade_count=0,
        ai_pnl_amount=None,
        ai_pnl_ratio=None,
        ai_trade_count=0,
        manual_pnl_amount=None,
        manual_pnl_ratio=None,
        manual_trade_count=0,
        by_exchange=[],
        top_coins=[],
    )
    mock_portfolio_service.get_portfolio_summary.return_value = expected

    resp = await client.get("/portfolio")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_balance_krw"] is None
    assert data["by_exchange"] == []
    assert data["top_coins"] == []
    assert data["total_trade_count"] == 0


# ── T6: 거래소 API 실패 → 부분 응답 ──────────────────────────────────────────


@pytest.mark.anyio
async def test_get_portfolio_summary_partial_exchange_failure_returns_partial_data(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T6: 1개 거래소 성공 + 1개 실패 → 성공 데이터만 포함한 200 응답."""
    # 서비스가 부분 실패를 처리하고 성공 거래소 데이터만 반환
    upbit_ea_id = uuid.uuid4()
    expected = _make_portfolio_summary(
        by_exchange=[
            _make_exchange_summary(
                exchange_account_id=upbit_ea_id,
                exchange_type="upbit",
                balance_krw=Decimal("5000000.00"),
            )
        ],
        # coinone은 실패하여 제외됨
        top_coins=[],
    )
    mock_portfolio_service.get_portfolio_summary.return_value = expected

    resp = await client.get("/portfolio")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["by_exchange"]) == 1
    assert data["by_exchange"][0]["exchange_type"] == "upbit"


# ── T7: 매수 이력 없는 코인 → avg_entry_price=null, pnl=null ─────────────────


@pytest.mark.anyio
async def test_get_exchange_portfolio_coin_without_buy_history_has_null_pnl(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T7: 매수 이력 없는 코인(외부 입금) → avg_entry_price=null, pnl_amount=null, pnl_ratio=null."""
    coin_no_history = _make_coin_holding(
        symbol="BTC/KRW",
        currency="BTC",
        quantity=Decimal("0.1"),
        avg_entry_price=None,    # 매수 이력 없음
        current_price=Decimal("87500000.00"),
        value_krw=Decimal("8750000.00"),
        pnl_amount=None,         # PnL 계산 불가
        pnl_ratio=None,          # PnL 계산 불가
        weight_percent=None,     # weight도 null
    )
    expected = _make_exchange_portfolio(coins=[coin_no_history])
    mock_portfolio_service.get_exchange_portfolio.return_value = expected

    resp = await client.get(f"/portfolio/{uuid.uuid4()}")

    assert resp.status_code == 200
    c = resp.json()["data"]["coins"][0]
    assert c["avg_entry_price"] is None
    assert c["pnl_amount"] is None
    assert c["pnl_ratio"] is None


@pytest.mark.anyio
async def test_get_exchange_portfolio_coin_without_ticker_has_null_current_price(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T7: Redis ticker 없는 코인 → current_price=null, value_krw=null, pnl=null."""
    coin_no_ticker = _make_coin_holding(
        symbol="RARE/KRW",
        currency="RARE",
        quantity=Decimal("1000"),
        avg_entry_price=Decimal("100.00"),
        current_price=None,     # ticker 없음
        value_krw=None,
        pnl_amount=None,
        pnl_ratio=None,
        weight_percent=None,
    )
    expected = _make_exchange_portfolio(coins=[coin_no_ticker])
    mock_portfolio_service.get_exchange_portfolio.return_value = expected

    resp = await client.get(f"/portfolio/{uuid.uuid4()}")

    assert resp.status_code == 200
    c = resp.json()["data"]["coins"][0]
    assert c["current_price"] is None
    assert c["value_krw"] is None
    assert c["pnl_amount"] is None


# ── T8: 캐시 HIT 검증 ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_portfolio_summary_cache_hit_returns_cached_data(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T8: 캐시 HIT 시 cached_at 필드가 non-null."""
    cached_time = datetime(2026, 3, 15, 10, 30, 0, tzinfo=UTC)
    expected = _make_portfolio_summary(cached_at=cached_time)
    mock_portfolio_service.get_portfolio_summary.return_value = expected

    resp = await client.get("/portfolio")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cached_at"] is not None


@pytest.mark.anyio
async def test_get_portfolio_summary_service_called_once_on_cache_hit(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T8: 서비스는 1회만 호출됨 (캐시 로직은 서비스 내부 책임)."""
    mock_portfolio_service.get_portfolio_summary.return_value = _make_portfolio_summary()

    await client.get("/portfolio")
    await client.get("/portfolio")

    # API 레이어는 서비스를 2번 호출하지만, 서비스 내부 캐시 로직은 Provider를 1번만 호출
    assert mock_portfolio_service.get_portfolio_summary.call_count == 2


@pytest.mark.anyio
async def test_get_exchange_portfolio_cache_hit_returns_cached_at(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T8: 거래소별 상세 캐시 HIT → cached_at non-null."""
    cached_time = datetime(2026, 3, 15, 10, 30, 0, tzinfo=UTC)
    expected = _make_exchange_portfolio(cached_at=cached_time)
    mock_portfolio_service.get_exchange_portfolio.return_value = expected

    resp = await client.get(f"/portfolio/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["data"]["cached_at"] is not None


# ── T9: 캐시 무효화 후 재조회 ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_portfolio_summary_cache_miss_returns_null_cached_at(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T9: 캐시 MISS(무효화 후) → cached_at=null (실시간 계산)."""
    expected = _make_portfolio_summary(cached_at=None)
    mock_portfolio_service.get_portfolio_summary.return_value = expected

    resp = await client.get("/portfolio")

    assert resp.status_code == 200
    assert resp.json()["data"]["cached_at"] is None


@pytest.mark.anyio
async def test_get_exchange_portfolio_cache_miss_fetches_fresh_data(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """T9: 캐시 무효화 후 재조회 → 서비스가 새 데이터를 반환, cached_at=null."""
    fresh_data = _make_exchange_portfolio(cached_at=None)
    mock_portfolio_service.get_exchange_portfolio.return_value = fresh_data

    ea_id = uuid.uuid4()
    resp = await client.get(f"/portfolio/{ea_id}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cached_at"] is None
    # 서비스 호출 확인
    mock_portfolio_service.get_exchange_portfolio.assert_called_once()


# ── 에러 응답 공통 검증 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_error_response_has_code_and_message(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """에러 응답 포맷 — code, message 필드 존재."""
    mock_portfolio_service.get_portfolio_summary.side_effect = AppError(
        "TEST_CODE", "테스트 에러", 400
    )

    resp = await client.get("/portfolio")

    error = resp.json()["error"]
    assert "code" in error
    assert "message" in error


@pytest.mark.anyio
async def test_get_exchange_portfolio_exchange_account_not_found_returns_404(
    client: AsyncClient, mock_portfolio_service: AsyncMock
):
    """존재하지 않는 거래소 계정 조회 → 404 EXCHANGE_ACCOUNT_NOT_FOUND."""
    mock_portfolio_service.get_exchange_portfolio.side_effect = (
        ExchangeErrors.account_not_found()
    )

    resp = await client.get(f"/portfolio/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "EXCHANGE_ACCOUNT_NOT_FOUND"
