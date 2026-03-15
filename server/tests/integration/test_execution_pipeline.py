"""ExecutionEngine 통합 파이프라인 테스트 — 5건.

Redis(AsyncMock) + Provider(Mock) + OrderRepository(Mock) + Beanie(patch) 조합.
실제 DrawdownManager, RiskManager, OrderTracker, TradeLogger 인스턴스 사용.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from datetime import UTC, datetime

from app.providers.enums import OrderMethod, OrderSide, OrderStatus
from app.providers.types import OrderResult
from app.trading.execution.drawdown_manager import DrawdownManager
from app.trading.execution.engine import ExecutionEngine
from app.trading.execution.order_tracker import OrderTracker
from app.trading.execution.risk_manager import RiskManager
from app.trading.execution.trade_logger import TradeLogger
from app.trading.execution.types import TradeExecutionContext

# ── 픽스처 헬퍼 ───────────────────────────────────────────────────────────────

USER_ID = str(uuid4())
ACCOUNT_ID = str(uuid4())
COIN_ID = str(uuid4())


def _make_risk_params(**overrides):
    p = {
        "max_investment_ratio": 0.10,
        "stop_loss_ratio": 0.02,
        "take_profit_ratio": 0.03,
        "daily_max_loss_ratio": 0.05,
        "max_active_positions": 3,
        "max_consecutive_losses": 3,
        "mdd_limit_ratio": 0.15,
        "win_rate_estimate": 0.5,
        "avg_rr_ratio": 1.5,
    }
    p.update(overrides)
    return p


def _make_signal(**overrides):
    s = {
        "strategy_name": "trend_ma",
        "action": "buy",
        "confidence": 0.80,
        "entry_price": 100_000_000.0,
        "exit_params": {
            "stop_loss": 97_000_000.0,
            "take_profit": 104_000_000.0,
            "stop_loss_atr_mult": 1.5,
            "take_profit_atr_mult": 2.0,
            "risk_reward_ratio": 1.5,
        },
        "strength": "strong",
        "position_scale": 1.0,
        "mtf_weight": 1.0,
        "conditions": [],
        "regime_type": "trend",
        "detail": "통합 테스트 신호",
    }
    s.update(overrides)
    return s


def _make_context(**overrides) -> TradeExecutionContext:
    ctx: TradeExecutionContext = {
        "user_id": USER_ID,
        "exchange_account_id": ACCOUNT_ID,
        "coin_id": COIN_ID,
        "market": "KRW-BTC",
        "symbol": "BTC/KRW",
        "signal": _make_signal(),
        "risk_params": _make_risk_params(),
        "total_capital": Decimal("10_000_000"),
        "available_balance": Decimal("10_000_000"),
    }
    ctx.update(overrides)
    return ctx


def _make_order_result(status=OrderStatus.FILLED) -> OrderResult:
    return OrderResult(
        exchange_order_id="exc-int-001",
        market="KRW-BTC",
        side=OrderSide.BUY,
        method=OrderMethod.MARKET,
        status=status,
        quantity=Decimal("0.001"),
        executed_quantity=Decimal("0.001"),
        avg_executed_price=Decimal("100_000_000"),
        fee=Decimal("50"),
        fee_currency="KRW",
        created_at=datetime.now(UTC),
        executed_at=None,
    )


def _make_db_order(order_result: OrderResult) -> MagicMock:
    order = MagicMock()
    order.id = uuid4()
    order.exchange_order_id = order_result.exchange_order_id
    order.status = order_result.status.value
    order.executed_quantity = order_result.executed_quantity
    order.executed_price = order_result.avg_executed_price
    order.fee = order_result.fee
    return order


def _build_engine_with_mocks(
    redis_hgetall: dict = None,
    redis_scard: int = 0,
    provider_result: OrderResult = None,
    log_entry_return=None,
) -> tuple[ExecutionEngine, AsyncMock]:
    """통합 테스트용 엔진 조립. Redis + Provider + OrderRepo + TradeLog mock."""
    redis = AsyncMock()
    redis.hgetall.return_value = redis_hgetall or {}
    redis.hset.return_value = True
    redis.expire.return_value = True
    redis.scard.return_value = redis_scard
    redis.sadd.return_value = 1
    redis.srem.return_value = 1

    or_result = provider_result or _make_order_result()
    db_order = _make_db_order(or_result)

    order_repo = AsyncMock()
    order_repo.create.return_value = db_order
    order_repo.update_status.return_value = None
    order_repo.update_after_execution.return_value = None
    order_repo.create_event.return_value = None
    order_repo.get_by_id.return_value = db_order

    provider = AsyncMock()
    provider.exchange_type = "upbit"
    provider.place_order.return_value = or_result
    provider.get_order.return_value = or_result
    provider.cancel_order.return_value = True

    engine = ExecutionEngine(
        risk_manager=RiskManager(),
        drawdown_manager=DrawdownManager(redis),
        order_tracker=OrderTracker(order_repo),
        trade_logger=TradeLogger(),
        provider=provider,
    )
    return engine, redis


# ── 통합 시나리오 ─────────────────────────────────────────────────────────────

class TestFullPipeline:
    @pytest.mark.anyio
    async def test_signal_to_filled_order(self):
        """풀 파이프라인: TradingSignal → 리스크 통과 → 사이징 → 주문 → 로그."""
        engine, redis = _build_engine_with_mocks()

        from bson import ObjectId
        mock_doc = AsyncMock()
        mock_doc.id = ObjectId()
        mock_doc.insert = AsyncMock(return_value=mock_doc)

        with patch("app.trading.execution.trade_logger.TradeLog", return_value=mock_doc):
            ctx = _make_context()
            result = await engine.execute(ctx)

        assert result["status"] in ("filled", "partial", "open")
        assert result["order_id"] is not None
        assert result["risk_check"]["allowed"] is True
        assert result["position_size"] is not None
        assert result["skipped_reason"] is None


class TestRiskBlockScenario:
    @pytest.mark.anyio
    async def test_daily_loss_exceeded_skips_trade(self):
        """일일 손실 5% 초과 → ExecutionResult(status='skipped')."""
        engine, _ = _build_engine_with_mocks(
            redis_hgetall={
                b"daily_loss_ratio": b"0.063",  # 6.3% > 5% 한도
                b"mdd_ratio": b"0.063",
                b"consecutive_losses": b"2",
                b"is_suspended": b"0",
                b"cooldown_until": b"",
                b"peak_balance": b"10000000.0",
                b"detail": "테스트".encode(),
            }
        )
        ctx = _make_context(risk_params=_make_risk_params(daily_max_loss_ratio=0.05))
        result = await engine.execute(ctx)

        assert result["status"] == "skipped"
        assert result["order_id"] is None
        assert "일일 손실" in result["skipped_reason"]

    @pytest.mark.anyio
    async def test_mdd_exceeded_suspends_trading(self):
        """MDD 15% 초과 → 거래 일시정지 (skipped)."""
        engine, _ = _build_engine_with_mocks(
            redis_hgetall={
                b"daily_loss_ratio": b"0.02",
                b"mdd_ratio": b"0.16",  # 16% > 15% 한도
                b"consecutive_losses": b"1",
                b"is_suspended": b"0",
                b"cooldown_until": b"",
                b"peak_balance": b"10000000.0",
                b"detail": b"",
            }
        )
        ctx = _make_context(risk_params=_make_risk_params(mdd_limit_ratio=0.15))
        result = await engine.execute(ctx)

        assert result["status"] == "skipped"
        assert "MDD" in result["skipped_reason"]


class TestConsecutiveLossCooldown:
    @pytest.mark.anyio
    async def test_three_consecutive_losses_then_blocked(self):
        """연속 3회 손실 기록 후 쿨다운 활성화 → 다음 execute() 차단."""
        redis = AsyncMock()
        redis.hset.return_value = True
        redis.expire.return_value = True
        redis.sadd.return_value = 1
        redis.scard.return_value = 0

        # 초기 상태: 연속 손실 2회, 이번이 3번째
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

        # 3번째 손실 기록
        new_state = await dm.record_trade_result(
            USER_ID, ACCOUNT_ID,
            pnl_ratio=-0.01,
            current_balance=Decimal("9_600_000"),
        )
        assert new_state["is_suspended"] is True
        assert new_state["cooldown_until"] is not None

        # 이후 get_state에서 쿨다운 상태 반환
        redis.hgetall.return_value = {
            b"daily_loss_ratio": b"0.05",
            b"mdd_ratio": b"0.04",
            b"consecutive_losses": b"3",
            b"is_suspended": b"1",
            b"cooldown_until": new_state["cooldown_until"].encode(),
            b"peak_balance": b"10000000.0",
            b"detail": b"",
        }

        # 다음 execute() 쿨다운으로 차단
        or_result = _make_order_result()
        db_order = _make_db_order(or_result)
        order_repo = AsyncMock()
        order_repo.create.return_value = db_order
        order_repo.get_by_id.return_value = db_order
        order_repo.update_status.return_value = None
        order_repo.update_after_execution.return_value = None
        order_repo.create_event.return_value = None
        provider = AsyncMock()
        provider.exchange_type = "upbit"
        provider.place_order.return_value = or_result

        engine = ExecutionEngine(
            risk_manager=RiskManager(),
            drawdown_manager=dm,
            order_tracker=OrderTracker(order_repo),
            trade_logger=TradeLogger(),
            provider=provider,
        )

        ctx = _make_context()
        with patch("app.trading.execution.trade_logger.TradeLog", return_value=AsyncMock(
            id=__import__("bson").ObjectId(), insert=AsyncMock(return_value=AsyncMock(id=__import__("bson").ObjectId()))
        )):
            result = await engine.execute(ctx)

        assert result["status"] == "skipped"
        assert "쿨다운" in result["skipped_reason"]


class TestPartialFillScenario:
    @pytest.mark.anyio
    async def test_partial_fill_then_timeout_cancels(self):
        """부분 체결 → 60초 폴링 → 타임아웃 → 잔량 취소."""
        redis = AsyncMock()
        redis.hgetall.return_value = {}
        redis.hset.return_value = True
        redis.expire.return_value = True
        redis.scard.return_value = 0
        redis.sadd.return_value = 1

        partial_result = _make_order_result(OrderStatus.PARTIAL)
        db_order = _make_db_order(partial_result)
        db_order.status = "partial"

        order_repo = AsyncMock()
        order_repo.create.return_value = db_order
        order_repo.get_by_id.return_value = db_order
        order_repo.update_status.return_value = None
        order_repo.update_after_execution.return_value = None
        order_repo.create_event.return_value = None

        provider = AsyncMock()
        provider.exchange_type = "upbit"
        provider.place_order.return_value = partial_result
        provider.get_order.return_value = partial_result  # 항상 partial
        provider.cancel_order.return_value = True

        mock_doc = AsyncMock()
        mock_doc.id = __import__("bson").ObjectId()
        mock_doc.insert = AsyncMock(return_value=mock_doc)

        engine = ExecutionEngine(
            risk_manager=RiskManager(),
            drawdown_manager=DrawdownManager(redis),
            order_tracker=OrderTracker(order_repo),
            trade_logger=TradeLogger(),
            provider=provider,
        )

        ctx = _make_context()
        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("app.trading.execution.order_tracker.PARTIAL_FILL_WAIT_SECONDS", 20),
            patch("app.trading.execution.order_tracker.PARTIAL_FILL_POLL_INTERVAL", 10),
            patch("app.trading.execution.trade_logger.TradeLog", return_value=mock_doc),
        ):
            result = await engine.execute(ctx)

        # 부분 체결 처리 후 취소까지 완료 → 주문 ID 존재
        assert result["order_id"] is not None
        provider.cancel_order.assert_awaited()
