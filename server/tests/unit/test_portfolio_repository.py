"""PortfolioRepository 단위 테스트."""
from __future__ import annotations

import uuid  # noqa: F401  (USER_ID, ACCOUNT_ID)
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.portfolio_repository import PortfolioRepository
from app.schemas.portfolio import AvgEntryPrice, TradeCounts


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def make_repo() -> tuple[PortfolioRepository, MagicMock]:
    """PortfolioRepository와 AsyncSession mock 반환."""
    db = MagicMock()
    db.execute = AsyncMock()
    repo = PortfolioRepository(db)
    return repo, db


def make_row(currency: str, avg_price: Decimal, total_buy_quantity: Decimal) -> MagicMock:
    row = MagicMock()
    row.currency = currency
    row.avg_price = avg_price
    row.total_buy_quantity = total_buy_quantity
    return row


def make_stats_row(total: int, ai_count: int, manual_count: int) -> MagicMock:
    row = MagicMock()
    row.total = total
    row.ai_count = ai_count
    row.manual_count = manual_count
    return row


USER_ID = uuid.uuid4()
ACCOUNT_ID = uuid.uuid4()
COIN1 = "BTC"
COIN2 = "ETH"


# ── get_avg_entry_prices ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_avg_entry_prices_single_coin() -> None:
    """단일 코인의 평균 매입가 정상 반환."""
    repo, db = make_repo()
    avg_price = Decimal("85000000")
    total_qty = Decimal("0.05")
    row = make_row(COIN1, avg_price, total_qty)
    result_mock = MagicMock()
    result_mock.all.return_value = [row]
    db.execute.return_value = result_mock

    result = await repo.get_avg_entry_prices(USER_ID, ACCOUNT_ID)

    assert COIN1 in result
    assert result[COIN1].avg_price == avg_price
    assert result[COIN1].total_buy_quantity == total_qty


@pytest.mark.anyio
async def test_get_avg_entry_prices_multiple_coins() -> None:
    """다중 코인의 평균 매입가 정상 반환."""
    repo, db = make_repo()
    row1 = make_row(COIN1, Decimal("85000000"), Decimal("0.05"))
    row2 = make_row(COIN2, Decimal("3500000"), Decimal("1.5"))
    result_mock = MagicMock()
    result_mock.all.return_value = [row1, row2]
    db.execute.return_value = result_mock

    result = await repo.get_avg_entry_prices(USER_ID, ACCOUNT_ID)

    assert len(result) == 2
    assert result[COIN1].avg_price == Decimal("85000000")
    assert result[COIN2].avg_price == Decimal("3500000")


@pytest.mark.anyio
async def test_get_avg_entry_prices_empty() -> None:
    """매수 이력 없으면 빈 dict 반환."""
    repo, db = make_repo()
    result_mock = MagicMock()
    result_mock.all.return_value = []
    db.execute.return_value = result_mock

    result = await repo.get_avg_entry_prices(USER_ID, ACCOUNT_ID)

    assert result == {}


@pytest.mark.anyio
async def test_get_avg_entry_prices_skips_null_avg_price() -> None:
    """avg_price가 None인 행은 결과에서 제외 (NULLIF 반환 케이스)."""
    repo, db = make_repo()
    row = MagicMock()
    row.currency = COIN1
    row.avg_price = None  # NULLIF → 0 나누기 방어
    row.total_buy_quantity = Decimal("0")
    result_mock = MagicMock()
    result_mock.all.return_value = [row]
    db.execute.return_value = result_mock

    result = await repo.get_avg_entry_prices(USER_ID, ACCOUNT_ID)

    assert result == {}


# ── get_trade_stats ───────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_trade_stats_normal() -> None:
    """정상 거래 통계 반환."""
    repo, db = make_repo()
    row = make_stats_row(total=42, ai_count=28, manual_count=14)
    result_mock = MagicMock()
    result_mock.one.return_value = row
    db.execute.return_value = result_mock

    result = await repo.get_trade_stats(USER_ID)

    assert isinstance(result, TradeCounts)
    assert result.total == 42
    assert result.ai_count == 28
    assert result.manual_count == 14


@pytest.mark.anyio
async def test_get_trade_stats_zero() -> None:
    """거래 없으면 모두 0."""
    repo, db = make_repo()
    row = make_stats_row(total=0, ai_count=0, manual_count=0)
    result_mock = MagicMock()
    result_mock.one.return_value = row
    db.execute.return_value = result_mock

    result = await repo.get_trade_stats(USER_ID)

    assert result.total == 0
    assert result.ai_count == 0
    assert result.manual_count == 0
