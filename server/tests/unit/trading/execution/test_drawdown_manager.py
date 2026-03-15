"""DrawdownManager 단위 테스트 — 10건.

Redis AsyncMock으로 실제 연결 없이 Hash/Set 동작 검증.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.trading.execution.drawdown_manager import DrawdownManager

USER_ID = "user-001"
ACCOUNT_ID = "acct-001"
DRAWDOWN_KEY = f"trading:drawdown:{USER_ID}:{ACCOUNT_ID}"
POSITIONS_KEY = f"trading:positions:{USER_ID}:{ACCOUNT_ID}"


def _make_redis(**hgetall_return) -> AsyncMock:
    """AsyncMock Redis 생성. hgetall 반환값 설정."""
    redis = AsyncMock()
    redis.hgetall.return_value = hgetall_return
    redis.hset.return_value = True
    redis.expire.return_value = True
    redis.sadd.return_value = 1
    redis.srem.return_value = 1
    redis.scard.return_value = 0
    return redis


class TestGetState:
    @pytest.mark.anyio
    async def test_no_key_returns_defaults(self):
        """Redis에 키 없으면 기본값 반환."""
        redis = _make_redis()  # hgetall 빈 dict 반환
        redis.hgetall.return_value = {}
        dm = DrawdownManager(redis)

        state = await dm.get_state(USER_ID, ACCOUNT_ID)
        assert state["daily_loss_ratio"] == 0.0
        assert state["mdd_ratio"] == 0.0
        assert state["consecutive_losses"] == 0
        assert state["is_suspended"] is False
        assert state["cooldown_until"] is None

    @pytest.mark.anyio
    async def test_existing_key_parses_values(self):
        """Redis에 키 있으면 저장된 값 파싱."""
        redis = _make_redis()
        redis.hgetall.return_value = {
            b"daily_loss_ratio": b"0.03",
            b"mdd_ratio": b"0.07",
            b"consecutive_losses": b"2",
            b"is_suspended": b"0",
            b"cooldown_until": b"",
            b"peak_balance": b"12000000.0",
            b"detail": "테스트".encode(),
        }
        dm = DrawdownManager(redis)

        state = await dm.get_state(USER_ID, ACCOUNT_ID)
        assert abs(state["daily_loss_ratio"] - 0.03) < 1e-9
        assert abs(state["mdd_ratio"] - 0.07) < 1e-9
        assert state["consecutive_losses"] == 2
        assert state["is_suspended"] is False


class TestRecordTradeResult:
    @pytest.mark.anyio
    async def test_profit_resets_consecutive_losses(self):
        """수익 거래 → consecutive_losses 리셋."""
        redis = _make_redis()
        redis.hgetall.return_value = {
            b"daily_loss_ratio": b"0.02",
            b"mdd_ratio": b"0.05",
            b"consecutive_losses": b"2",
            b"is_suspended": b"0",
            b"cooldown_until": b"",
            b"peak_balance": b"10000000.0",
            b"detail": b"",
        }
        dm = DrawdownManager(redis)

        state = await dm.record_trade_result(
            USER_ID, ACCOUNT_ID,
            pnl_ratio=0.03,               # 수익
            current_balance=Decimal("10_300_000"),
        )
        assert state["consecutive_losses"] == 0
        assert state["is_suspended"] is False

    @pytest.mark.anyio
    async def test_loss_increments_daily_and_consecutive(self):
        """손실 거래 → daily_loss + consecutive_losses 증가."""
        redis = _make_redis()
        redis.hgetall.return_value = {
            b"daily_loss_ratio": b"0.01",
            b"mdd_ratio": b"0.01",
            b"consecutive_losses": b"1",
            b"is_suspended": b"0",
            b"cooldown_until": b"",
            b"peak_balance": b"10000000.0",
            b"detail": b"",
        }
        dm = DrawdownManager(redis)

        state = await dm.record_trade_result(
            USER_ID, ACCOUNT_ID,
            pnl_ratio=-0.02,              # 2% 손실
            current_balance=Decimal("9_800_000"),
        )
        assert abs(state["daily_loss_ratio"] - 0.03) < 1e-9   # 0.01 + 0.02
        assert state["consecutive_losses"] == 2

    @pytest.mark.anyio
    async def test_three_consecutive_losses_triggers_cooldown(self):
        """3회 연속 손실 → is_suspended=True + cooldown_until 설정."""
        redis = _make_redis()
        redis.hgetall.return_value = {
            b"daily_loss_ratio": b"0.04",
            b"mdd_ratio": b"0.04",
            b"consecutive_losses": b"2",
            b"is_suspended": b"0",
            b"cooldown_until": b"",
            b"peak_balance": b"10000000.0",
            b"detail": b"",
        }
        dm = DrawdownManager(redis)

        state = await dm.record_trade_result(
            USER_ID, ACCOUNT_ID,
            pnl_ratio=-0.01,
            current_balance=Decimal("9_600_000"),
        )
        assert state["is_suspended"] is True
        assert state["cooldown_until"] is not None
        assert state["consecutive_losses"] == 3


class TestPositionTracking:
    @pytest.mark.anyio
    async def test_add_position_calls_sadd_and_sets_ttl(self):
        """add_position → Redis SADD + POSITIONS_SET_TTL expire 호출."""
        from app.trading.execution.constants import POSITIONS_SET_TTL
        redis = _make_redis()
        dm = DrawdownManager(redis)

        await dm.add_position(USER_ID, ACCOUNT_ID, "order-123")
        redis.sadd.assert_awaited_once_with(POSITIONS_KEY, "order-123")
        redis.expire.assert_awaited_with(POSITIONS_KEY, POSITIONS_SET_TTL)

    @pytest.mark.anyio
    async def test_remove_position_calls_srem(self):
        """remove_position → Redis SREM 호출."""
        redis = _make_redis()
        dm = DrawdownManager(redis)

        await dm.remove_position(USER_ID, ACCOUNT_ID, "order-123")
        redis.srem.assert_awaited_once_with(POSITIONS_KEY, "order-123")

    @pytest.mark.anyio
    async def test_get_active_position_count(self):
        """get_active_position_count → Redis SCARD."""
        redis = _make_redis()
        redis.scard.return_value = 2
        dm = DrawdownManager(redis)

        count = await dm.get_active_position_count(USER_ID, ACCOUNT_ID)
        assert count == 2
        redis.scard.assert_awaited_once_with(POSITIONS_KEY)


class TestDailyReset:
    @pytest.mark.anyio
    async def test_reset_daily_clears_daily_loss_ratio(self):
        """reset_daily → daily_loss_ratio=0, 나머지 유지."""
        redis = _make_redis()
        redis.hgetall.return_value = {
            b"daily_loss_ratio": b"0.04",
            b"mdd_ratio": b"0.08",
            b"consecutive_losses": b"1",
            b"is_suspended": b"0",
            b"cooldown_until": b"",
            b"peak_balance": b"9500000.0",
            b"detail": b"",
        }
        dm = DrawdownManager(redis)

        await dm.reset_daily(USER_ID, ACCOUNT_ID)
        # hset 호출 시 daily_loss_ratio=0 이어야 함
        call_kwargs = redis.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        assert mapping["daily_loss_ratio"] == "0.0"
        assert mapping["mdd_ratio"] == "0.08"  # MDD는 유지


class TestSetSuspension:
    @pytest.mark.anyio
    async def test_set_suspension_marks_suspended(self):
        """set_suspension → is_suspended=True + cooldown_until 설정."""
        redis = _make_redis()
        redis.hgetall.return_value = {}
        dm = DrawdownManager(redis)

        await dm.set_suspension(USER_ID, ACCOUNT_ID, reason="MDD 한도 초과", cooldown_seconds=3600)
        call_kwargs = redis.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        assert mapping["is_suspended"] == "1"
        assert mapping["cooldown_until"]  # ISO datetime 설정됨
