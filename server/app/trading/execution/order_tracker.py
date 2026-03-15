"""주문 생성/상태 추적 — OrderRepository + 거래소 폴링.

ExchangeRestProvider + OrderRepository 의존.
OrderService를 import하지 않음 (의존 방향: api → services → trading/).
OrderRepository.create(is_ai_order=True) 직접 호출 — 별도 update_ai_flag() 불필요.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from uuid import UUID

from app.models.trading import TradeOrder
from app.providers.base import ExchangeRestProvider
from app.providers.enums import OrderMethod, OrderSide, OrderStatus
from app.providers.types import Order, OrderResult
from app.repositories.order_repository import OrderRepository

from .constants import PARTIAL_FILL_POLL_INTERVAL, PARTIAL_FILL_WAIT_SECONDS
from .exceptions import OrderExecutionError

logger = logging.getLogger(__name__)


class OrderTracker:
    """주문 생성 + 부분 체결 추적.

    1. OrderRepository.create(is_ai_order=True)로 TradeOrder INSERT (status=pending)
    2. Provider.place_order() 호출
    3. 결과 반영 (status, exchange_order_id, executed_* 필드)
    4. 부분 체결 시 60초 대기 + 10초 폴링
    5. TradeOrderEvent 이력 기록
    """

    def __init__(self, order_repo: OrderRepository) -> None:
        self._order_repo = order_repo
        self._last_market: str = ""  # wait_for_fill 폴링용 (set_market()으로 갱신)

    async def create_order(
        self,
        provider: ExchangeRestProvider,
        *,
        user_id: UUID,
        exchange_account_id: UUID,
        coin_id: UUID,
        market: str,
        side: OrderSide,
        method: OrderMethod,
        quantity: Decimal,
        amount: Decimal | None,
        price: Decimal | None,
    ) -> tuple[TradeOrder, OrderResult]:
        """주문 생성 + 거래소 전송 + DB 저장.

        1. self._order_repo.create(is_ai_order=True) → PENDING INSERT
        2. Provider.place_order()
        3. 결과 반영 (status, exchange_order_id, executed_* 필드)
        4. TradeOrderEvent 기록
        5. 실패 시 status=failed + 예외 raise

        Returns:
            (TradeOrder, OrderResult): DB 레코드 + 거래소 응답.

        Raises:
            OrderExecutionError: 거래소 주문 실패.
        """
        # 1. DB에 PENDING 상태로 INSERT
        trade_order = await self._order_repo.create(
            user_id=user_id,
            exchange_account_id=exchange_account_id,
            coin_id=coin_id,
            order_type=side.value,
            order_method=method.value,
            price=price,
            quantity=quantity,
            amount=amount,
            status=OrderStatus.PENDING.value,
            is_ai_order=True,
        )
        order_id = trade_order.id
        logger.info("order created in DB: %s (pending)", order_id)

        # 2. 거래소에 주문 전송
        exchange_order = Order(
            market=market,
            side=side,
            method=method,
            quantity=quantity,
            price=price,
        )

        try:
            result: OrderResult = await provider.place_order(exchange_order)
        except Exception as exc:
            logger.error("place_order failed for order %s: %s", order_id, exc)
            await self._order_repo.update_status(order_id, OrderStatus.FAILED.value)
            await self._order_repo.create_event(
                trade_order_id=order_id,
                event_type="order_failed",
                from_status=OrderStatus.PENDING.value,
                to_status=OrderStatus.FAILED.value,
                detail={"error": str(exc)},
            )
            raise OrderExecutionError(str(exc), exchange_error=exc)

        # 3. 결과 반영
        new_status = result.status.value
        await self._order_repo.update_after_execution(
            order_id=order_id,
            status=new_status,
            exchange_order_id=result.exchange_order_id,
            executed_quantity=result.executed_quantity,
            executed_price=result.avg_executed_price,
            fee=result.fee,
            fee_currency=result.fee_currency,
            executed_at=result.executed_at,
        )

        # 4. 이벤트 기록
        await self._order_repo.create_event(
            trade_order_id=order_id,
            event_type="order_placed",
            from_status=OrderStatus.PENDING.value,
            to_status=new_status,
            detail={
                "exchange_order_id": result.exchange_order_id,
                "status": new_status,
                "executed_quantity": str(result.executed_quantity),
            },
        )

        # DB 레코드 최신화
        refreshed = await self._order_repo.get_by_id(order_id)
        if refreshed is None:
            refreshed = trade_order  # fallback (flush 완료 상태)

        logger.info(
            "order placed: db=%s exchange=%s status=%s",
            order_id, result.exchange_order_id, new_status,
        )
        return refreshed, result

    async def wait_for_fill(
        self,
        provider: ExchangeRestProvider,
        trade_order: TradeOrder,
    ) -> TradeOrder:
        """부분 체결 대기 + 폴링 + 잔량 처리.

        1. 60초 대기 (PARTIAL_FILL_WAIT_SECONDS)
        2. 10초 간격 provider.get_order() 폴링
        3. filled → 즉시 반환
        4. 60초 초과 시 provider.cancel_order()로 잔량 취소
        5. 체결된 수량 보존, DB 업데이트

        Returns:
            갱신된 TradeOrder.
        """
        order_id = trade_order.id
        market = trade_order.exchange_account.coin.symbol if hasattr(trade_order, 'exchange_account') else ""
        exchange_order_id = trade_order.exchange_order_id

        if not exchange_order_id:
            logger.warning("wait_for_fill: no exchange_order_id for %s", order_id)
            return trade_order

        # market 코드 확보 (TradeOrder에 market 컬럼이 없으므로 저장된 coin 심볼 활용 불가)
        # order_tracker는 create_order 호출 시 market을 알고 있으므로 별도로 전달받는 방식이 이상적이나
        # 설계서 시그니처 준수 — TradeOrder에서 최대한 추론
        # 실제 폴링은 exchange_order_id + market 필요
        # market은 엔진에서 context.market을 통해 알 수 있음
        # 여기서는 간단히 처리: market 정보는 호출자(engine.py)가 _place_and_track에서 전달

        elapsed = 0
        while elapsed < PARTIAL_FILL_WAIT_SECONDS:
            await asyncio.sleep(PARTIAL_FILL_POLL_INTERVAL)
            elapsed += PARTIAL_FILL_POLL_INTERVAL

            try:
                result = await provider.get_order(
                    market=self._last_market,  # set by _set_market()
                    exchange_order_id=exchange_order_id,
                )
            except Exception as exc:
                logger.warning("get_order poll failed (%s): %s", exchange_order_id, exc)
                continue

            new_status = result.status.value
            if new_status == OrderStatus.FILLED.value:
                await self._order_repo.update_after_execution(
                    order_id=order_id,
                    status=new_status,
                    executed_quantity=result.executed_quantity,
                    executed_price=result.avg_executed_price,
                    fee=result.fee,
                    executed_at=result.executed_at,
                )
                await self._order_repo.create_event(
                    trade_order_id=order_id,
                    event_type="order_filled",
                    from_status=OrderStatus.PARTIAL.value,
                    to_status=new_status,
                    detail={"executed_quantity": str(result.executed_quantity)},
                )
                logger.info("order %s filled (partial→filled)", order_id)
                break

        else:
            # 60초 초과 — 잔량 취소
            logger.warning(
                "partial fill timeout for %s, cancelling remainder", exchange_order_id
            )
            await self._cancel_remaining(
                provider,
                market=self._last_market,
                exchange_order_id=exchange_order_id,
            )
            # 체결된 수량 보존 + 상태 업데이트
            try:
                final = await provider.get_order(
                    market=self._last_market,
                    exchange_order_id=exchange_order_id,
                )
                final_status = final.status.value
                await self._order_repo.update_after_execution(
                    order_id=order_id,
                    status=final_status,
                    executed_quantity=final.executed_quantity,
                    executed_price=final.avg_executed_price,
                    fee=final.fee,
                )
                await self._order_repo.create_event(
                    trade_order_id=order_id,
                    event_type="order_cancelled_partial",
                    from_status=OrderStatus.PARTIAL.value,
                    to_status=final_status,
                    detail={"executed_quantity": str(final.executed_quantity)},
                )
            except Exception as exc:
                logger.error("final get_order failed after cancel: %s", exc)

        refreshed = await self._order_repo.get_by_id(order_id)
        return refreshed if refreshed is not None else trade_order

    def set_market(self, market: str) -> None:
        """폴링용 마켓 코드 설정 (engine.py에서 호출)."""
        self._last_market = market

    @staticmethod
    async def _cancel_remaining(
        provider: ExchangeRestProvider,
        market: str,
        exchange_order_id: str,
    ) -> bool:
        """미체결 잔량 취소."""
        try:
            result = await provider.cancel_order(market, exchange_order_id)
            return result
        except Exception as exc:
            logger.warning("cancel_order failed for %s: %s", exchange_order_id, exc)
            return False
