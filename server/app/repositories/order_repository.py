"""주문 Repository — TradeOrder CRUD + TradingFee 조회."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.trade_order_event import TradeOrderEvent
from app.models.trading import TradeOrder
from app.models.trading_fee import TradingFee

if TYPE_CHECKING:
    from app.models.coin import Coin


class OrderRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID,
        coin_id: uuid.UUID,
        order_type: str,
        order_method: str,
        price: Decimal | None,
        quantity: Decimal | None,
        amount: Decimal | None,
        status: str,
        is_ai_order: bool = False,
    ) -> TradeOrder:
        """TradeOrder INSERT."""
        order = TradeOrder(
            user_id=user_id,
            exchange_account_id=exchange_account_id,
            coin_id=coin_id,
            order_type=order_type,
            order_method=order_method,
            price=price,
            quantity=quantity,
            amount=amount,
            status=status,
            is_ai_order=is_ai_order,
        )
        self._db.add(order)
        await self._db.flush()
        await self._db.refresh(order)
        return order

    async def get_by_id(self, order_id: uuid.UUID) -> TradeOrder | None:
        """PK 조회."""
        result = await self._db.execute(
            select(TradeOrder).where(TradeOrder.id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_coin(self, order_id: uuid.UUID) -> TradeOrder | None:
        """selectinload(TradeOrder.coin) 포함 조회."""
        result = await self._db.execute(
            select(TradeOrder)
            .where(TradeOrder.id == order_id)
            .options(selectinload(TradeOrder.coin))
        )
        return result.scalar_one_or_none()

    async def get_by_ids(self, order_ids: list[uuid.UUID]) -> list[TradeOrder]:
        """IN 조회 (batch-cancel용). selectinload(coin) 포함."""
        result = await self._db.execute(
            select(TradeOrder)
            .where(TradeOrder.id.in_(order_ids))
            .options(selectinload(TradeOrder.coin))
        )
        return list(result.scalars().all())

    async def list_by_user(
        self,
        *,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID | None = None,
        coin_id: uuid.UUID | None = None,
        status: str | None = None,
        side: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[TradeOrder], int]:
        """사용자별 주문 목록 + COUNT."""
        base_query = (
            select(TradeOrder)
            .where(TradeOrder.user_id == user_id)
            .options(selectinload(TradeOrder.coin))
        )
        count_query = select(func.count()).select_from(TradeOrder).where(
            TradeOrder.user_id == user_id
        )

        if exchange_account_id is not None:
            base_query = base_query.where(
                TradeOrder.exchange_account_id == exchange_account_id
            )
            count_query = count_query.where(
                TradeOrder.exchange_account_id == exchange_account_id
            )
        if coin_id is not None:
            base_query = base_query.where(TradeOrder.coin_id == coin_id)
            count_query = count_query.where(TradeOrder.coin_id == coin_id)
        if status is not None:
            base_query = base_query.where(TradeOrder.status == status)
            count_query = count_query.where(TradeOrder.status == status)
        if side is not None:
            base_query = base_query.where(TradeOrder.order_type == side)
            count_query = count_query.where(TradeOrder.order_type == side)
        if from_dt is not None:
            base_query = base_query.where(TradeOrder.created_at >= from_dt)
            count_query = count_query.where(TradeOrder.created_at >= from_dt)
        if to_dt is not None:
            base_query = base_query.where(TradeOrder.created_at <= to_dt)
            count_query = count_query.where(TradeOrder.created_at <= to_dt)

        total_result = await self._db.execute(count_query)
        total = total_result.scalar_one()

        offset = (page - 1) * size
        result = await self._db.execute(
            base_query.order_by(TradeOrder.created_at.desc()).offset(offset).limit(size)
        )
        orders = list(result.scalars().all())
        return orders, total

    async def update_status(self, order_id: uuid.UUID, status: str) -> None:
        """상태만 업데이트."""
        await self._db.execute(
            update(TradeOrder)
            .where(TradeOrder.id == order_id)
            .values(status=status)
        )
        await self._db.flush()

    async def update_after_execution(
        self,
        *,
        order_id: uuid.UUID,
        status: str,
        exchange_order_id: str | None = None,
        executed_quantity: Decimal | None = None,
        executed_price: Decimal | None = None,
        fee: Decimal | None = None,
        fee_rate: Decimal | None = None,
        fee_currency: str | None = None,
        executed_at: datetime | None = None,
    ) -> None:
        """주문 실행 후 상태 + 체결 정보 일괄 업데이트."""
        values: dict = {"status": status}
        if exchange_order_id is not None:
            values["exchange_order_id"] = exchange_order_id
        if executed_quantity is not None:
            values["executed_quantity"] = executed_quantity
        if executed_price is not None:
            values["executed_price"] = executed_price
        if fee is not None:
            values["fee"] = fee
        if fee_rate is not None:
            values["fee_rate"] = fee_rate
        if fee_currency is not None:
            values["fee_currency"] = fee_currency
        if executed_at is not None:
            values["executed_at"] = executed_at
        await self._db.execute(
            update(TradeOrder).where(TradeOrder.id == order_id).values(**values)
        )
        await self._db.flush()

    async def get_coin(self, coin_id: uuid.UUID) -> Coin | None:
        """Coin 단건 조회 (주문 생성 시 market_code 확보용)."""
        from app.models.coin import Coin

        result = await self._db.execute(
            select(Coin).where(Coin.id == coin_id)
        )
        return result.scalar_one_or_none()

    async def get_trading_fee(
        self, exchange_type: str, tier: int = 0,
    ) -> TradingFee | None:
        """trading_fees 테이블에서 수수료율 조회."""
        result = await self._db.execute(
            select(TradingFee).where(
                TradingFee.exchange_type == exchange_type,
                TradingFee.fee_tier == tier,
            )
        )
        return result.scalar_one_or_none()

    async def get_open_orders_for_account(
        self, user_id: uuid.UUID, exchange_account_id: uuid.UUID,
    ) -> list[TradeOrder]:
        """계정별 미체결 주문 조회.

        WHERE status IN ('pending', 'open', 'partial')
        인덱스: ix_trade_orders_active (PARTIAL)
        """
        result = await self._db.execute(
            select(TradeOrder)
            .where(
                TradeOrder.user_id == user_id,
                TradeOrder.exchange_account_id == exchange_account_id,
                TradeOrder.status.in_(["pending", "open", "partial"]),
            )
            .options(selectinload(TradeOrder.coin))
        )
        return list(result.scalars().all())

    async def count_active_ai_orders(self, user_id: uuid.UUID) -> int:
        """사용자의 미체결 AI 주문 수 (전 계정 합산).

        RiskManager.check()에서 최대 포지션 수 검증용.
        WHERE is_ai_order=True AND status IN ('open', 'partial')
        인덱스: ix_trade_orders_active (PARTIAL) 활용.
        """
        result = await self._db.execute(
            select(func.count())
            .select_from(TradeOrder)
            .where(
                TradeOrder.user_id == user_id,
                TradeOrder.is_ai_order.is_(True),
                TradeOrder.status.in_(["open", "partial"]),
            )
        )
        return result.scalar_one()

    async def create_event(
        self,
        *,
        trade_order_id: uuid.UUID,
        event_type: str,
        from_status: str | None = None,
        to_status: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """TradeOrderEvent INSERT (상태 변경 이력 기록)."""
        event = TradeOrderEvent(
            trade_order_id=trade_order_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            detail=detail,
        )
        self._db.add(event)
        await self._db.flush()
