"""거래 로그 기록 — MongoDB trade_logs.

기존 TradeLog Document(documents/trading_logs.py) 재사용.
Beanie Document CRUD — DB 주입 불필요 (Beanie가 내부 관리).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from beanie import PydanticObjectId
from bson import Decimal128

from app.documents.trading_logs import TradeLog
from app.trading.strategy.types import TradingSignal

from .types import PositionSizeResult

logger = logging.getLogger(__name__)


class TradeLogger:
    """MongoDB 거래 로그 기록.

    Beanie Document 직접 사용 — 생성자/DB 주입 없음.
    TradeLog(...).insert() 방식.
    """

    async def log_entry(
        self,
        trade_order_id: UUID,
        signal: TradingSignal,
        position_size: PositionSizeResult,
        *,
        user_id: UUID,
        coin_symbol: str,
        market_code: str,
        exchange_type: str,
        order_type: str,
        entry_price: Decimal,
        quantity: Decimal,
        fee: Decimal,
        ai_decision_id: PydanticObjectId | None = None,
    ) -> PydanticObjectId:
        """진입 거래 로그 기록.

        Returns:
            MongoDB document ID.
        """
        doc = TradeLog(
            user_id=user_id,
            trade_order_id=trade_order_id,
            coin_symbol=coin_symbol,
            market_code=market_code,
            exchange_type=exchange_type,
            order_type=order_type,
            order_method="market",  # AI 주문은 시장가 기본
            price=Decimal128(str(entry_price)),
            quantity=Decimal128(str(quantity)),
            fee=Decimal128(str(fee)),
            is_ai_order=True,
            market_regime=signal.get("regime_type"),
            strategy_name=signal.get("strategy_name"),
            ai_decision_id=ai_decision_id,
            reasoning_summary=signal.get("detail", "")[:200] if signal.get("detail") else None,
            strategy_params_snapshot={
                "strength": signal.get("strength"),
                "confidence": signal.get("confidence"),
                "mtf_weight": signal.get("mtf_weight"),
                "position_scale": signal.get("position_scale"),
                "sizing_method": position_size["method"],
                "investment_ratio": position_size["investment_ratio"],
            },
            entry_price=Decimal128(str(entry_price)),
            status="open",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        result = await doc.insert()
        doc_id: PydanticObjectId = result.id
        logger.info(
            "trade_log inserted: %s (order=%s symbol=%s)",
            doc_id, trade_order_id, coin_symbol,
        )
        return doc_id

    async def update_on_close(
        self,
        trade_log_id: PydanticObjectId,
        exit_price: Decimal,
        pnl_amount: Decimal,
        pnl_ratio: Decimal,
        holding_minutes: int,
    ) -> None:
        """청산 시 로그 업데이트 (status: open → closed)."""
        doc = await TradeLog.get(trade_log_id)
        if doc is None:
            logger.warning("trade_log not found: %s", trade_log_id)
            return

        await doc.set({
            TradeLog.pnl_amount: Decimal128(str(pnl_amount)),
            TradeLog.pnl_ratio: Decimal128(str(pnl_ratio)),
            TradeLog.holding_minutes: holding_minutes,
            TradeLog.status: "closed",
            TradeLog.updated_at: datetime.now(UTC),
        })
        logger.info(
            "trade_log closed: %s pnl=%s ratio=%s",
            trade_log_id, pnl_amount, pnl_ratio,
        )
