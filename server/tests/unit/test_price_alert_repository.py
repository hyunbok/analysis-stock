"""PriceAlertRepository 단위 테스트.

설계서: docs/tasks/v1-21-price-alert-system-plan.md §8.1
테스트: DB CRUD + mark_triggered (~10건)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.price_alert_repository import PriceAlertRepository


# ── 상수 / 헬퍼 ───────────────────────────────────────────────────────────────

USER_ID = uuid.uuid4()
COIN_ID = uuid.uuid4()
ALERT_ID = uuid.uuid4()
EXCHANGE_ACCOUNT_ID = uuid.uuid4()


def _make_alert_row(
    alert_id: uuid.UUID = ALERT_ID,
    user_id: uuid.UUID = USER_ID,
    coin_id: uuid.UUID = COIN_ID,
    condition: str = "above",
    target_price: Decimal = Decimal("85000000"),
    is_triggered: bool = False,
    is_active: bool = True,
) -> MagicMock:
    alert = MagicMock()
    alert.id = alert_id
    alert.user_id = user_id
    alert.coin_id = coin_id
    alert.condition = condition
    alert.target_price = target_price
    alert.is_triggered = is_triggered
    alert.is_active = is_active
    alert.exchange_account_id = None
    alert.triggered_at = None
    alert.created_at = datetime.now(UTC)
    alert.updated_at = datetime.now(UTC)
    alert.coin = MagicMock()
    alert.coin.symbol = "BTC/KRW"
    alert.coin.name_ko = "비트코인"
    return alert


def _make_repo() -> tuple[PriceAlertRepository, MagicMock]:
    db = MagicMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    repo = PriceAlertRepository(db)
    return repo, db


def _make_scalars_result(items: list) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    scalars.first.return_value = items[0] if items else None
    result.scalars.return_value = scalars
    return result


def _make_scalar_result(value) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


# ── create ────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_calls_db_add_flush_refresh() -> None:
    """알림 INSERT → db.add + flush + refresh 순서 호출."""
    repo, db = _make_repo()

    async def _mock_refresh(obj, attributes=None):
        obj.coin = MagicMock()
        obj.coin.symbol = "BTC/KRW"
        obj.coin.name_ko = "비트코인"

    db.refresh = AsyncMock(side_effect=_mock_refresh)

    result = await repo.create(
        user_id=USER_ID,
        coin_id=COIN_ID,
        exchange_account_id=None,
        condition="above",
        target_price=Decimal("85000000"),
    )

    db.add.assert_called_once()
    db.flush.assert_called_once()
    db.refresh.assert_called_once()
    assert result.condition == "above"
    assert result.coin.symbol == "BTC/KRW"


# ── get_by_id ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_by_id_returns_alert_with_coin() -> None:
    """ID로 알림 조회 → coin 로드 포함."""
    repo, db = _make_repo()
    alert = _make_alert_row()
    db.execute.return_value = _make_scalars_result([alert])

    result = await repo.get_by_id(ALERT_ID)

    assert result is not None
    assert result.id == ALERT_ID
    db.execute.assert_called_once()


@pytest.mark.anyio
async def test_get_by_id_not_found_returns_none() -> None:
    """존재하지 않는 ID → None."""
    repo, db = _make_repo()
    db.execute.return_value = _make_scalars_result([])

    result = await repo.get_by_id(uuid.uuid4())

    assert result is None


# ── get_by_user_and_id ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_by_user_and_id_owned_returns_alert() -> None:
    """본인 소유 알림 → 반환."""
    repo, db = _make_repo()
    alert = _make_alert_row()
    db.execute.return_value = _make_scalars_result([alert])

    result = await repo.get_by_user_and_id(user_id=USER_ID, alert_id=ALERT_ID)

    assert result is not None
    assert result.user_id == USER_ID


@pytest.mark.anyio
async def test_get_by_user_and_id_other_user_returns_none() -> None:
    """타인 소유 → None."""
    repo, db = _make_repo()
    db.execute.return_value = _make_scalars_result([])

    result = await repo.get_by_user_and_id(user_id=USER_ID, alert_id=uuid.uuid4())

    assert result is None


# ── get_by_user ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_by_user_returns_all_alerts() -> None:
    """사용자 전체 알림 조회 (active=None)."""
    repo, db = _make_repo()
    alerts = [_make_alert_row(), _make_alert_row(alert_id=uuid.uuid4())]
    db.execute.return_value = _make_scalars_result(alerts)

    result = await repo.get_by_user(USER_ID, active=None)

    assert len(result) == 2


@pytest.mark.anyio
async def test_get_by_user_active_filter_returns_only_active() -> None:
    """active=True 필터 → 활성 알림만."""
    repo, db = _make_repo()
    active_alert = _make_alert_row(is_active=True)
    db.execute.return_value = _make_scalars_result([active_alert])

    result = await repo.get_by_user(USER_ID, active=True)

    assert len(result) == 1
    assert all(a.is_active is True for a in result)


# ── mark_triggered ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_mark_triggered_success_returns_true() -> None:
    """is_triggered=False인 알림 업데이트 → True 반환."""
    repo, db = _make_repo()
    execute_result = MagicMock()
    execute_result.rowcount = 1
    db.execute.return_value = execute_result

    result = await repo.mark_triggered(ALERT_ID)

    assert result is True
    db.execute.assert_called_once()


@pytest.mark.anyio
async def test_mark_triggered_already_triggered_returns_false() -> None:
    """이미 is_triggered=True → affected_rows=0 → False 반환."""
    repo, db = _make_repo()
    execute_result = MagicMock()
    execute_result.rowcount = 0
    db.execute.return_value = execute_result

    result = await repo.mark_triggered(ALERT_ID)

    assert result is False


# ── count_by_user ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_count_by_user_returns_correct_count() -> None:
    """사용자 알림 수 조회."""
    repo, db = _make_repo()
    db.execute.return_value = _make_scalar_result(15)

    count = await repo.count_by_user(USER_ID)

    assert count == 15


# ── get_active_untriggered_by_market ─────────────────────────────────────────


@pytest.mark.anyio
async def test_get_active_untriggered_by_market_returns_matching_alerts() -> None:
    """exchange_type + market_code 기준 활성 미트리거 알림 조회."""
    repo, db = _make_repo()
    alerts = [_make_alert_row(is_active=True, is_triggered=False)]
    db.execute.return_value = _make_scalars_result(alerts)

    result = await repo.get_active_untriggered_by_market("upbit", "KRW-BTC")

    assert len(result) == 1
    assert result[0].is_active is True
    assert result[0].is_triggered is False
