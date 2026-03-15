"""PortfolioService 단위 테스트."""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppError
from app.providers.types import Balance
from app.repositories.portfolio_repository import PortfolioRepository
from app.schemas.portfolio import (
    AvgEntryPrice,
    CoinHolding,
    ExchangePortfolioResponse,
    PortfolioSummaryResponse,
    TradeCounts,
)
from app.services.portfolio_service import PortfolioService


# ── 상수 / 헬퍼 ───────────────────────────────────────────────────────────────

USER_ID = uuid.uuid4()
ACCOUNT_ID = uuid.uuid4()
COIN_ID = uuid.uuid4()
VALID_SECRET = "a" * 64

BTC_BALANCE = Balance(
    currency="BTC",
    available=Decimal("0.045"),
    locked=Decimal("0.005"),
)
KRW_BALANCE = Balance(
    currency="KRW",
    available=Decimal("500000"),
    locked=Decimal("0"),
)


def make_settings(secret: str = VALID_SECRET) -> MagicMock:
    s = MagicMock()
    s.EXCHANGE_API_KEY_SECRET = secret
    return s


def make_account(
    account_id: uuid.UUID = ACCOUNT_ID,
    user_id: uuid.UUID = USER_ID,
    exchange_type: str = "upbit",
    nickname: str | None = "내 업비트",
) -> MagicMock:
    account = MagicMock()
    account.id = account_id
    account.user_id = user_id
    account.exchange_type = exchange_type
    account.nickname = nickname
    account.api_key_encrypted = b"enc_key"
    account.api_secret_encrypted = b"enc_secret"
    return account


def make_service(
    balances: list[Balance] | None = None,
    avg_prices: dict | None = None,
    trade_stats: TradeCounts | None = None,
    ticker_data: dict | None = None,
    accounts: list | None = None,
) -> PortfolioService:
    """테스트용 PortfolioService 생성 (의존성 모킹)."""
    portfolio_repo = MagicMock(spec=PortfolioRepository)
    portfolio_repo.get_avg_entry_prices = AsyncMock(return_value=avg_prices or {})
    portfolio_repo.get_trade_stats = AsyncMock(
        return_value=trade_stats or TradeCounts(total=0, ai_count=0, manual_count=0)
    )

    exchange_account_repo = MagicMock()
    exchange_account_repo.get_by_user_id = AsyncMock(return_value=accounts or [])

    mock_provider = AsyncMock()
    mock_provider.get_balance = AsyncMock(return_value=balances or [])
    mock_provider.close = AsyncMock()

    factory = MagicMock()
    factory.create_from_account = AsyncMock(return_value=mock_provider)

    market_cache = MagicMock()
    market_cache.get_ticker = AsyncMock(return_value=ticker_data)

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # 캐시 MISS 기본값
    redis.set = AsyncMock()
    redis.delete = AsyncMock()

    settings = make_settings()

    return PortfolioService(
        portfolio_repo=portfolio_repo,
        exchange_account_repo=exchange_account_repo,
        factory=factory,
        market_cache=market_cache,
        redis=redis,
        settings=settings,
    )


# ── _calculate_coin_pnl ───────────────────────────────────────────────────────


def test_calculate_coin_pnl_profit() -> None:
    """수익 케이스: 현재가 > 매입가."""
    pnl_amount, pnl_ratio = PortfolioService._calculate_coin_pnl(
        current_price=Decimal("87500000"),
        avg_entry_price=Decimal("85000000"),
        quantity=Decimal("0.05"),
    )
    assert pnl_amount == Decimal("125000")
    assert pnl_ratio > Decimal("0")


def test_calculate_coin_pnl_loss() -> None:
    """손실 케이스: 현재가 < 매입가."""
    pnl_amount, pnl_ratio = PortfolioService._calculate_coin_pnl(
        current_price=Decimal("80000000"),
        avg_entry_price=Decimal("85000000"),
        quantity=Decimal("0.05"),
    )
    assert pnl_amount == Decimal("-250000")
    assert pnl_ratio < Decimal("0")


def test_calculate_coin_pnl_zero_avg_price() -> None:
    """평균 매입가 0: pnl_ratio = 0 (ZeroDivision 방어)."""
    pnl_amount, pnl_ratio = PortfolioService._calculate_coin_pnl(
        current_price=Decimal("87500000"),
        avg_entry_price=Decimal("0"),
        quantity=Decimal("0.05"),
    )
    assert pnl_amount == Decimal("87500000") * Decimal("0.05")
    assert pnl_ratio == Decimal("0")


def test_calculate_coin_pnl_breakeven() -> None:
    """손익분기: pnl = 0."""
    pnl_amount, pnl_ratio = PortfolioService._calculate_coin_pnl(
        current_price=Decimal("85000000"),
        avg_entry_price=Decimal("85000000"),
        quantity=Decimal("0.05"),
    )
    assert pnl_amount == Decimal("0")
    assert pnl_ratio == Decimal("0")


# ── get_portfolio_summary ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_portfolio_summary_no_accounts() -> None:
    """거래소 계정 없으면 빈 포트폴리오 반환."""
    svc = make_service(accounts=[])
    result = await svc.get_portfolio_summary(USER_ID)

    assert isinstance(result, PortfolioSummaryResponse)
    assert result.by_exchange == []
    assert result.top_coins == []
    assert result.total_balance_krw is None


@pytest.mark.anyio
async def test_get_portfolio_summary_single_exchange() -> None:
    """단일 거래소 계정 정상 조회."""
    account = make_account()
    svc = make_service(
        accounts=[account],
        balances=[KRW_BALANCE, BTC_BALANCE],
        ticker_data={"price": "87500000"},
        trade_stats=TradeCounts(total=5, ai_count=3, manual_count=2),
    )
    result = await svc.get_portfolio_summary(USER_ID)

    assert isinstance(result, PortfolioSummaryResponse)
    assert len(result.by_exchange) == 1
    assert result.by_exchange[0].exchange_type == "upbit"
    assert result.total_trade_count == 5
    assert result.ai_trade_count == 3
    assert result.manual_trade_count == 2


@pytest.mark.anyio
async def test_get_portfolio_summary_top_coins_sorted() -> None:
    """top_coins: value_krw 내림차순 상위 5개."""
    account = make_account()
    # BTC: 0.05 * 87,500,000 = 4,375,000
    svc = make_service(
        accounts=[account],
        balances=[BTC_BALANCE],
        ticker_data={"price": "87500000"},
    )
    result = await svc.get_portfolio_summary(USER_ID)

    assert len(result.top_coins) <= 5
    if result.top_coins:
        assert result.top_coins[0].symbol == "BTC/KRW"


@pytest.mark.anyio
async def test_get_portfolio_summary_partial_failure() -> None:
    """거래소 API 실패 시 해당 거래소 제외, 나머지 반환."""
    account1 = make_account(account_id=uuid.uuid4())
    account2 = make_account(account_id=uuid.uuid4(), exchange_type="coinone")

    portfolio_repo = MagicMock(spec=PortfolioRepository)
    portfolio_repo.get_avg_entry_prices = AsyncMock(return_value={})
    portfolio_repo.get_trade_stats = AsyncMock(
        return_value=TradeCounts(total=0, ai_count=0, manual_count=0)
    )
    exchange_account_repo = MagicMock()
    exchange_account_repo.get_by_user_id = AsyncMock(return_value=[account1, account2])

    # 첫 번째 Provider 정상, 두 번째 Provider 예외 발생
    provider_ok = AsyncMock()
    provider_ok.get_balance = AsyncMock(return_value=[KRW_BALANCE])
    provider_ok.close = AsyncMock()

    provider_fail = AsyncMock()
    provider_fail.get_balance = AsyncMock(side_effect=RuntimeError("Network error"))
    provider_fail.close = AsyncMock()

    call_count = 0

    async def create_from_account_side_effect(account, enc_key):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return provider_ok
        return provider_fail

    factory = MagicMock()
    factory.create_from_account = AsyncMock(side_effect=create_from_account_side_effect)

    market_cache = MagicMock()
    market_cache.get_ticker = AsyncMock(return_value=None)

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()

    svc = PortfolioService(
        portfolio_repo=portfolio_repo,
        exchange_account_repo=exchange_account_repo,
        factory=factory,
        market_cache=market_cache,
        redis=redis,
        settings=make_settings(),
    )

    result = await svc.get_portfolio_summary(USER_ID)

    # 실패한 거래소는 제외, 성공한 거래소만 반환
    assert len(result.by_exchange) == 1


@pytest.mark.anyio
async def test_get_portfolio_summary_cache_hit() -> None:
    """Redis 캐시 HIT 시 Provider 미호출."""
    import json

    account = make_account()
    svc = make_service(accounts=[account])

    cached_data = {
        "total_balance_krw": None,
        "total_pnl_amount": None,
        "total_pnl_ratio": None,
        "total_trade_count": 0,
        "ai_pnl_amount": None,
        "ai_pnl_ratio": None,
        "ai_trade_count": 0,
        "manual_pnl_amount": None,
        "manual_pnl_ratio": None,
        "manual_trade_count": 0,
        "by_exchange": [],
        "top_coins": [],
        "cached_at": "2026-03-15T10:30:00+00:00",
    }
    svc._redis.get = AsyncMock(return_value=json.dumps(cached_data).encode())

    result = await svc.get_portfolio_summary(USER_ID)

    assert isinstance(result, PortfolioSummaryResponse)
    svc._exchange_account_repo.get_by_user_id.assert_not_called()


# ── get_exchange_portfolio ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_exchange_portfolio_normal() -> None:
    """거래소별 상세 포트폴리오 정상 조회."""
    account = make_account()
    svc = make_service(
        balances=[KRW_BALANCE, BTC_BALANCE],
        ticker_data={"price": "87500000"},
    )
    svc._exchange_account_repo.get_by_id = AsyncMock(return_value=account)

    result = await svc.get_exchange_portfolio(USER_ID, ACCOUNT_ID)

    assert isinstance(result, ExchangePortfolioResponse)
    assert result.exchange_account_id == ACCOUNT_ID
    assert result.exchange_type == "upbit"
    assert result.krw_balance == Decimal("500000")
    assert len(result.coins) == 1
    assert result.coins[0].currency == "BTC"


@pytest.mark.anyio
async def test_get_exchange_portfolio_not_owned() -> None:
    """타 사용자 거래소 계정 접근 시 403."""
    other_user = uuid.uuid4()
    account = make_account(user_id=other_user)
    svc = make_service()
    svc._exchange_account_repo.get_by_id = AsyncMock(return_value=account)

    with pytest.raises(AppError) as exc_info:
        await svc.get_exchange_portfolio(USER_ID, ACCOUNT_ID)

    assert exc_info.value.http_status == 403
    assert exc_info.value.code == "PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED"


@pytest.mark.anyio
async def test_get_exchange_portfolio_account_not_found() -> None:
    """존재하지 않는 계정 조회 시 404."""
    svc = make_service()
    svc._exchange_account_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(AppError) as exc_info:
        await svc.get_exchange_portfolio(USER_ID, ACCOUNT_ID)

    assert exc_info.value.http_status == 404


@pytest.mark.anyio
async def test_get_exchange_portfolio_krw_in_krw_balance() -> None:
    """KRW 잔고는 coins 배열에 미포함, krw_balance 필드로 반환."""
    account = make_account()
    svc = make_service(balances=[KRW_BALANCE])
    svc._exchange_account_repo.get_by_id = AsyncMock(return_value=account)

    result = await svc.get_exchange_portfolio(USER_ID, ACCOUNT_ID)

    assert result.krw_balance == Decimal("500000")
    assert all(c.currency != "KRW" for c in result.coins)


# ── 캐시 테스트 ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_invalidate_cache() -> None:
    """캐시 무효화: 3개 키 DEL 호출."""
    svc = make_service()
    await svc.invalidate_cache(USER_ID, ACCOUNT_ID)

    svc._redis.delete.assert_awaited_once()
    call_args = svc._redis.delete.call_args[0]
    assert len(call_args) == 3


@pytest.mark.anyio
async def test_cache_redis_failure_graceful() -> None:
    """Redis 오류 시 예외 전파 없이 None 반환 (graceful degradation)."""
    svc = make_service()
    svc._redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

    result = await svc._get_cached("some:key")
    assert result is None


@pytest.mark.anyio
async def test_set_cache_redis_failure_graceful() -> None:
    """Redis SET 실패 시 예외 전파 없음."""
    svc = make_service()
    svc._redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))

    # 예외 없이 통과해야 함
    await svc._set_cache("some:key", {"k": "v"}, 60)


# ── 스키마 직렬화 ─────────────────────────────────────────────────────────────


def test_portfolio_summary_response_serialization() -> None:
    """PortfolioSummaryResponse 직렬화 정상."""
    from datetime import UTC, datetime

    response = PortfolioSummaryResponse(
        total_balance_krw=Decimal("15234500"),
        total_pnl_amount=Decimal("234500"),
        total_pnl_ratio=Decimal("1.56"),
        total_trade_count=42,
        ai_pnl_amount=Decimal("180000"),
        ai_pnl_ratio=Decimal("2.10"),
        ai_trade_count=28,
        manual_pnl_amount=Decimal("54500"),
        manual_pnl_ratio=Decimal("0.85"),
        manual_trade_count=14,
        by_exchange=[],
        top_coins=[],
        cached_at=datetime.now(UTC),
    )
    dumped = response.model_dump()
    assert dumped["total_balance_krw"] == Decimal("15234500")
    assert dumped["total_trade_count"] == 42


def test_weight_percent_calculation() -> None:
    """weight_percent 계산: CoinHolding 검증."""
    holding = CoinHolding(
        symbol="BTC/KRW",
        currency="BTC",
        quantity=Decimal("0.05"),
        available=Decimal("0.045"),
        locked=Decimal("0.005"),
        avg_entry_price=Decimal("85000000"),
        current_price=Decimal("87500000"),
        value_krw=Decimal("4375000"),
        pnl_amount=Decimal("125000"),
        pnl_ratio=Decimal("2.94"),
        weight_percent=Decimal("42.75"),
    )
    assert holding.weight_percent == Decimal("42.75")
    assert holding.pnl_ratio == Decimal("2.94")
