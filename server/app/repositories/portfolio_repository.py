"""포트폴리오 계산용 PG 조회 전용 레포지토리."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coin import Coin
from app.models.trading import TradeOrder
from app.schemas.portfolio import AvgEntryPrice, TradeCounts


class PortfolioRepository:
    """포트폴리오 계산용 PG 조회 전용 레포지토리.

    TradeOrder 테이블 SELECT 전용 — 쓰기 없음.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_avg_entry_prices(
        self,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID,
    ) -> dict[str, AvgEntryPrice]:
        """거래소 계정별 코인 가중 평균 매입가 계산 (VWAP).

        Coin 테이블 JOIN으로 currency(기축 통화) 키를 직접 반환한다.
        매도 수량은 고려하지 않음. 매도 후에도 평균 매입가는 변하지 않는 것이
        국내 거래소 표준 (업비트, 코인원 동일). 보유 수량은 get_balance()에서 실시간 조회.

        SQL:
            SELECT split_part(coins.symbol, '/', 1) AS currency,
                   SUM(executed_quantity * executed_price)
                       / NULLIF(SUM(executed_quantity), 0) AS avg_price,
                   SUM(executed_quantity) AS total_buy_quantity
            FROM trade_orders
            JOIN coins ON trade_orders.coin_id = coins.id
            WHERE user_id = :user_id
              AND exchange_account_id = :exchange_account_id
              AND order_type = 'buy'
              AND status = 'filled'
              AND executed_quantity > 0
            GROUP BY split_part(coins.symbol, '/', 1)

        Args:
            user_id: 사용자 ID.
            exchange_account_id: 거래소 계정 ID.

        Returns:
            {currency: AvgEntryPrice(avg_price, total_buy_quantity)}
            e.g. {"BTC": AvgEntryPrice(avg_price=85000000, total_buy_quantity=0.05)}

        Note:
            인덱스: ix_trade_orders_user_account_status_created
        """
        currency_col = func.split_part(Coin.symbol, "/", 1).label("currency")
        stmt = (
            select(
                currency_col,
                (
                    func.sum(TradeOrder.executed_quantity * TradeOrder.executed_price)
                    / func.nullif(func.sum(TradeOrder.executed_quantity), 0)
                ).label("avg_price"),
                func.sum(TradeOrder.executed_quantity).label("total_buy_quantity"),
            )
            .join(Coin, TradeOrder.coin_id == Coin.id)
            .where(
                TradeOrder.user_id == user_id,
                TradeOrder.exchange_account_id == exchange_account_id,
                TradeOrder.order_type == "buy",
                TradeOrder.status == "filled",
                TradeOrder.executed_quantity > 0,
            )
            .group_by(currency_col)
        )
        result = await self._db.execute(stmt)
        rows = result.all()
        return {
            row.currency: AvgEntryPrice(
                avg_price=row.avg_price,
                total_buy_quantity=row.total_buy_quantity,
            )
            for row in rows
            if row.avg_price is not None
        }

    async def get_trade_stats(
        self,
        user_id: uuid.UUID,
    ) -> TradeCounts:
        """전체/AI/수동 매매 통계 집계 (filled 주문 기준).

        SQL:
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE is_ai_order = true) AS ai_count,
                COUNT(*) FILTER (WHERE is_ai_order = false) AS manual_count
            FROM trade_orders
            WHERE user_id = :user_id AND status = 'filled'

        Args:
            user_id: 사용자 ID.

        Returns:
            TradeCounts(total, ai_count, manual_count)
        """
        stmt = select(
            func.count().label("total"),
            func.count().filter(TradeOrder.is_ai_order.is_(True)).label("ai_count"),
            func.count().filter(TradeOrder.is_ai_order.is_(False)).label("manual_count"),
        ).where(
            TradeOrder.user_id == user_id,
            TradeOrder.status == "filled",
        )
        result = await self._db.execute(stmt)
        row = result.one()
        return TradeCounts(
            total=row.total,
            ai_count=row.ai_count,
            manual_count=row.manual_count,
        )
