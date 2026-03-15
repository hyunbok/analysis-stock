"""TradeLogger 단위 테스트 — 3건.

Beanie Document를 Mock하여 MongoDB 의존성 없이 검증.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from bson import ObjectId

from app.trading.execution.trade_logger import TradeLogger
from app.trading.execution.types import PositionSizeResult

from .conftest import make_trading_signal


def _make_position_size() -> PositionSizeResult:
    return PositionSizeResult(
        method="fixed_fractional",
        quantity=Decimal("0.001"),
        investment_amount=Decimal("100_000"),
        investment_ratio=0.01,
        stop_loss_ratio=0.03,
        kelly_fraction=None,
        strength_multiplier=1.0,
        position_scale=1.0,
        detail="FF: ...",
    )


class TestLogEntry:
    @pytest.mark.anyio
    async def test_log_entry_inserts_document(self):
        """log_entry → TradeLog.insert() 호출 + ObjectId 반환."""
        doc_id = ObjectId()
        mock_doc_instance = AsyncMock()
        mock_doc_instance.id = doc_id

        mock_trade_log_cls = MagicMock()
        mock_trade_log_cls.return_value = mock_doc_instance
        mock_doc_instance.insert = AsyncMock(return_value=mock_doc_instance)

        with patch("app.trading.execution.trade_logger.TradeLog", mock_trade_log_cls):
            logger = TradeLogger()
            result = await logger.log_entry(
                trade_order_id=uuid4(),
                signal=make_trading_signal(),
                position_size=_make_position_size(),
                user_id=uuid4(),
                coin_symbol="BTC",
                market_code="KRW-BTC",
                exchange_type="upbit",
                order_type="buy",
                entry_price=Decimal("100_000_000"),
                quantity=Decimal("0.001"),
                fee=Decimal("50"),
            )

        mock_doc_instance.insert.assert_awaited_once()
        assert result == doc_id

    @pytest.mark.anyio
    async def test_log_entry_field_mapping(self):
        """log_entry → TradeLog 생성 시 필드 올바르게 매핑."""
        mock_doc_instance = AsyncMock()
        mock_doc_instance.id = ObjectId()
        mock_doc_instance.insert = AsyncMock(return_value=mock_doc_instance)

        captured_kwargs = {}

        def capture_init(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_doc_instance

        mock_trade_log_cls = MagicMock(side_effect=capture_init)

        signal = make_trading_signal(
            strategy_name="trend_ma",
            strength="strong",
            regime_type="trend",
        )
        pos_size = _make_position_size()
        user_id = uuid4()
        trade_order_id = uuid4()

        with patch("app.trading.execution.trade_logger.TradeLog", mock_trade_log_cls):
            logger = TradeLogger()
            await logger.log_entry(
                trade_order_id=trade_order_id,
                signal=signal,
                position_size=pos_size,
                user_id=user_id,
                coin_symbol="BTC",
                market_code="KRW-BTC",
                exchange_type="upbit",
                order_type="buy",
                entry_price=Decimal("100_000_000"),
                quantity=Decimal("0.001"),
                fee=Decimal("50"),
            )

        assert captured_kwargs["user_id"] == user_id
        assert captured_kwargs["trade_order_id"] == trade_order_id
        assert captured_kwargs["coin_symbol"] == "BTC"
        assert captured_kwargs["is_ai_order"] is True
        assert captured_kwargs["status"] == "open"


class TestUpdateOnClose:
    @pytest.mark.anyio
    async def test_update_on_close_sets_closed_status(self):
        """update_on_close → TradeLog.get() + doc.set() 호출, status='closed' 확인."""
        doc_id = ObjectId()
        mock_doc = AsyncMock()

        with patch("app.trading.execution.trade_logger.TradeLog") as mock_cls:
            mock_cls.get = AsyncMock(return_value=mock_doc)

            logger = TradeLogger()
            await logger.update_on_close(
                trade_log_id=doc_id,
                exit_price=Decimal("105_000_000"),
                pnl_amount=Decimal("50_000"),
                pnl_ratio=Decimal("0.05"),
                holding_minutes=120,
            )

        mock_cls.get.assert_awaited_once_with(doc_id)
        mock_doc.set.assert_awaited_once()
        # set() 인자에 status='closed' 포함 확인
        set_call_args = mock_doc.set.call_args[0][0]  # 첫 번째 positional dict
        values = list(set_call_args.values())
        assert "closed" in values
        assert 120 in values  # holding_minutes
