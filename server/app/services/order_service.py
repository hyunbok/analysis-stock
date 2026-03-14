"""주문 생성/조회/취소 서비스 + 주문 상태 머신."""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from uuid import UUID

from app.core.config import Settings
from app.core.exceptions import AppError, CoinErrors, ExchangeErrors, OrderErrors
from app.models.trading import TradeOrder
from app.providers.enums import OrderMethod, OrderSide, OrderStatus
from app.providers.exceptions import (
    ExchangeAuthError,
    ExchangeError,
    ExchangeInsufficientBalanceError,
    ExchangeOrderError,
    ExchangePermissionError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from app.providers.factory import ExchangeProviderFactory
from app.providers.types import Order, OrderResult
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.order import (
    BatchCancelFailure,
    BatchCancelRequest,
    BatchCancelResponse,
    CreateOrderRequest,
    OrderListQuery,
    OrderResponse,
    PaginatedOrders,
)

logger = logging.getLogger(__name__)


class OrderStateMachine:
    """주문 상태 전이 규칙 관리."""

    _TRANSITIONS: dict[str, set[str]] = {
        "pending": {"open", "filled", "failed", "cancelled"},
        "open": {"filled", "partial", "cancelled"},
        "partial": {"filled", "cancelled"},
    }

    _CANCELLABLE: set[str] = {"pending", "open", "partial"}

    @classmethod
    def validate_transition(cls, current: str, target: str) -> None:
        """상태 전이 가능 여부 검증.

        Raises:
            AppError(INVALID_ORDER_TRANSITION): 허용되지 않는 전이
        """
        allowed = cls._TRANSITIONS.get(current, set())
        if target not in allowed:
            raise OrderErrors.invalid_status_transition(current, target)

    @classmethod
    def can_cancel(cls, status: str) -> bool:
        """취소 가능 상태인지 확인."""
        return status in cls._CANCELLABLE


class OrderService:
    """주문 생성/조회/취소 비즈니스 로직."""

    def __init__(
        self,
        order_repo: OrderRepository,
        exchange_account_repo: ExchangeAccountRepository,
        factory: ExchangeProviderFactory,
        settings: Settings,
    ) -> None:
        self._order_repo = order_repo
        self._exchange_account_repo = exchange_account_repo
        self._factory = factory
        self._settings = settings

    # ── 주문 생성 ──────────────────────────────────────────────────────

    async def create_order(
        self, user_id: UUID, request: CreateOrderRequest,
    ) -> OrderResponse:
        """주문 생성 → 거래소 전송 → DB 업데이트.

        1. 계정 소유권 + 코인 존재 확인
        2. TradeOrder INSERT (status=PENDING)
        3. Provider 생성 + place_order() 호출
        4. 결과에 따라 상태 전이 + DB 업데이트
        5. 실패 시 status=FAILED + 에러 raise
        """
        # 1. 계정 조회 + 소유권 확인
        account = await self._exchange_account_repo.get_by_id(
            request.exchange_account_id
        )
        if account is None or account.user_id != user_id:
            raise ExchangeErrors.account_not_found()

        # 2. 코인 조회 → market_code 확보
        coin = await self._order_repo.get_coin(request.coin_id)
        if coin is None:
            raise CoinErrors.not_found()

        # 3. DB INSERT (PENDING)
        order = await self._order_repo.create(
            user_id=user_id,
            exchange_account_id=request.exchange_account_id,
            coin_id=request.coin_id,
            order_type=request.side.value,
            order_method=request.method.value,
            price=request.price,
            quantity=request.quantity,
            amount=request.amount,
            status="pending",
        )

        # 4. Provider 생성 + 주문 실행
        provider = None
        try:
            enc_key = bytes.fromhex(self._settings.EXCHANGE_API_KEY_SECRET)
            provider = await self._factory.create_from_account(account, enc_key)

            provider_order = self._build_provider_order(coin.market_code, request)
            result = await provider.place_order(provider_order)

            # 5. 성공: 상태 전이 + DB 업데이트
            new_status = self._determine_status(result)
            OrderStateMachine.validate_transition("pending", new_status)

            # 수수료율 조회
            fee_rate = await self._get_fee_rate(
                provider, coin.market_code, request.method.value
            )

            await self._order_repo.update_after_execution(
                order_id=order.id,
                status=new_status,
                exchange_order_id=result.exchange_order_id,
                executed_quantity=result.executed_quantity,
                executed_price=result.avg_executed_price,
                fee=result.fee,
                fee_rate=fee_rate,
                fee_currency=result.fee_currency,
                executed_at=result.executed_at,
            )

            await self._order_repo.create_event(
                trade_order_id=order.id,
                event_type="status_changed",
                from_status="pending",
                to_status=new_status,
                detail={
                    "exchange_order_id": result.exchange_order_id,
                    "executed_quantity": str(result.executed_quantity),
                },
            )

        except ExchangeError as exc:
            # 6. 실패: FAILED로 전이
            await self._order_repo.update_status(order.id, "failed")
            await self._order_repo.create_event(
                trade_order_id=order.id,
                event_type="failed",
                from_status="pending",
                to_status="failed",
                detail={"error": str(exc)},
            )
            raise self._map_exchange_error(exc)
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass

        return await self._build_order_response(order.id)

    # ── 주문 목록 ──────────────────────────────────────────────────────

    async def list_orders(
        self, user_id: UUID, query: OrderListQuery,
    ) -> PaginatedOrders:
        """사용자 주문 내역 조회 (필터 + 페이지네이션)."""
        status_str = query.status.value if query.status is not None else None
        side_str = query.side.value if query.side is not None else None
        orders, total = await self._order_repo.list_by_user(
            user_id=user_id,
            exchange_account_id=query.exchange_account_id,
            coin_id=query.coin_id,
            status=status_str,
            side=side_str,
            from_dt=query.from_dt,
            to_dt=query.to_dt,
            page=query.page,
            size=query.size,
        )
        items = [self._to_response(o) for o in orders]
        return PaginatedOrders.build(
            items=items, total=total, page=query.page, size=query.size
        )

    # ── 주문 상세 ──────────────────────────────────────────────────────

    async def get_order(
        self, user_id: UUID, order_id: UUID,
    ) -> OrderResponse:
        """단일 주문 상세 조회."""
        order = await self._order_repo.get_by_id_with_coin(order_id)
        if order is None or order.user_id != user_id:
            raise OrderErrors.not_found()
        return self._to_response(order)

    # ── 주문 취소 ──────────────────────────────────────────────────────

    async def cancel_order(
        self, user_id: UUID, order_id: UUID,
    ) -> OrderResponse:
        """단건 주문 취소.

        1. 소유권 + 취소 가능 상태 확인
        2. Provider 취소 API 호출
        3. 상태 전이 → CANCELLED (부분 체결 보존)
        """
        order = await self._order_repo.get_by_id_with_coin(order_id)
        if order is None or order.user_id != user_id:
            raise OrderErrors.not_found()

        if not OrderStateMachine.can_cancel(order.status):
            raise OrderErrors.cannot_cancel(order.status)

        # PENDING 상태 (아직 거래소 미전송) → DB만 업데이트
        if order.status == "pending":
            await self._order_repo.update_status(order.id, "cancelled")
            await self._order_repo.create_event(
                trade_order_id=order.id,
                event_type="cancelled",
                from_status="pending",
                to_status="cancelled",
            )
            return await self._build_order_response(order.id)

        # OPEN/PARTIAL → 거래소 취소 API 호출
        account = await self._exchange_account_repo.get_by_id(
            order.exchange_account_id
        )
        if account is None:
            raise ExchangeErrors.account_not_found()
        provider = None
        try:
            enc_key = bytes.fromhex(self._settings.EXCHANGE_API_KEY_SECRET)
            provider = await self._factory.create_from_account(account, enc_key)

            success = await provider.cancel_order(
                order.coin.market_code, order.exchange_order_id
            )

            if success:
                await self._order_repo.update_status(order.id, "cancelled")
                await self._order_repo.create_event(
                    trade_order_id=order.id,
                    event_type="cancelled",
                    from_status=order.status,
                    to_status="cancelled",
                )
            else:
                # 이미 체결된 주문 → 상태 동기화
                await self._order_repo.update_status(order.id, "filled")
                await self._order_repo.create_event(
                    trade_order_id=order.id,
                    event_type="synced",
                    from_status=order.status,
                    to_status="filled",
                    detail={"reason": "already_filled"},
                )

        except ExchangeError as exc:
            raise self._map_exchange_error(exc)
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass

        return await self._build_order_response(order.id)

    # ── 일괄 취소 ──────────────────────────────────────────────────────

    async def batch_cancel(
        self, user_id: UUID, request: BatchCancelRequest,
    ) -> BatchCancelResponse:
        """미체결 주문 일괄 취소 (부분 성공 허용).

        asyncio.gather로 병렬 처리, 개별 실패는 failed 목록에 포함.
        """
        success_ids: list[UUID] = []
        failures: list[BatchCancelFailure] = []

        # 소유권 일괄 확인
        orders = await self._order_repo.get_by_ids(request.order_ids)
        order_map = {o.id: o for o in orders}

        for oid in request.order_ids:
            if oid not in order_map or order_map[oid].user_id != user_id:
                failures.append(
                    BatchCancelFailure(order_id=oid, reason="주문을 찾을 수 없습니다.")
                )

        cancellable_ids = [
            oid
            for oid in request.order_ids
            if oid in order_map
            and order_map[oid].user_id == user_id
            and OrderStateMachine.can_cancel(order_map[oid].status)
        ]

        # 취소 불가 상태 필터링
        for oid in request.order_ids:
            if (
                oid in order_map
                and order_map[oid].user_id == user_id
                and not OrderStateMachine.can_cancel(order_map[oid].status)
            ):
                failures.append(
                    BatchCancelFailure(
                        order_id=oid,
                        reason=f"취소 불가 상태: {order_map[oid].status}",
                    )
                )

        # 병렬 취소
        async def _cancel_single(oid: UUID) -> UUID | BatchCancelFailure:
            try:
                await self.cancel_order(user_id, oid)
                return oid
            except AppError as e:
                return BatchCancelFailure(order_id=oid, reason=e.message)

        results = await asyncio.gather(
            *[_cancel_single(oid) for oid in cancellable_ids],
            return_exceptions=True,
        )

        for oid, r in zip(cancellable_ids, results):
            if isinstance(r, UUID):
                success_ids.append(r)
            elif isinstance(r, BatchCancelFailure):
                failures.append(r)
            elif isinstance(r, Exception):
                logger.error("batch_cancel_unexpected_error", exc_info=r)
                failures.append(BatchCancelFailure(order_id=oid, reason=str(r)))

        return BatchCancelResponse(
            success_count=len(success_ids),
            failed_count=len(failures),
            success_ids=success_ids,
            failed=failures,
        )

    # ── Private 헬퍼 ───────────────────────────────────────────────────

    async def _build_order_response(self, order_id: UUID) -> OrderResponse:
        """TradeOrder + Coin JOIN 조회 → OrderResponse 변환."""
        order = await self._order_repo.get_by_id_with_coin(order_id)
        return self._to_response(order)

    @staticmethod
    def _to_response(order: TradeOrder) -> OrderResponse:
        """TradeOrder ORM → OrderResponse 스키마 변환."""
        from app.providers.enums import ExchangeType, OrderMethod, OrderSide, OrderStatus

        return OrderResponse(
            id=order.id,
            exchange_account_id=order.exchange_account_id,
            coin_id=order.coin_id,
            coin_symbol=order.coin.symbol,
            exchange_type=ExchangeType(order.coin.exchange_type),
            side=OrderSide(order.order_type),
            method=OrderMethod(order.order_method),
            status=OrderStatus(order.status),
            price=order.price,
            quantity=order.quantity,
            amount=order.amount,
            executed_quantity=order.executed_quantity,
            executed_price=order.executed_price,
            fee=order.fee,
            fee_rate=order.fee_rate,
            fee_currency=order.fee_currency,
            exchange_order_id=order.exchange_order_id,
            is_ai_order=order.is_ai_order,
            created_at=order.created_at,
            updated_at=order.updated_at,
            executed_at=order.executed_at,
        )

    @staticmethod
    def _build_provider_order(
        market_code: str, request: CreateOrderRequest,
    ) -> Order:
        """CreateOrderRequest → providers/types.py Order 변환.

        시장가 매수: price = amount (KRW 총액), quantity = 0 (placeholder)
        """
        if request.method == OrderMethod.MARKET and request.side == OrderSide.BUY:
            return Order(
                market=market_code,
                side=OrderSide.BUY,
                method=OrderMethod.MARKET,
                quantity=Decimal("0"),
                price=request.amount,  # Upbit: ord_type=price, price=KRW
            )
        return Order(
            market=market_code,
            side=request.side,
            method=request.method,
            quantity=request.quantity,
            price=request.price,
        )

    @staticmethod
    def _determine_status(result: OrderResult) -> str:
        """OrderResult → DB status 결정."""
        if result.status == OrderStatus.FILLED:
            return "filled"
        elif result.status == OrderStatus.PARTIAL:
            return "partial"
        else:
            return "open"

    async def _get_fee_rate(
        self,
        provider: object,
        market: str,
        method: str,
    ) -> Decimal | None:
        """수수료율 조회. Provider → DB fallback."""
        try:
            trading_fee = await provider.get_trading_fee(market)  # type: ignore[union-attr]
            return trading_fee.taker_fee if method == "market" else trading_fee.maker_fee
        except (ExchangeError, NotImplementedError, AttributeError):
            return await self._get_fallback_fee_rate(
                provider.exchange_type.value, method  # type: ignore[union-attr]
            )

    async def _get_fallback_fee_rate(
        self, exchange_type: str, method: str,
    ) -> Decimal | None:
        """trading_fees 테이블에서 기본(tier=0) 수수료율 조회."""
        fee = await self._order_repo.get_trading_fee(exchange_type, tier=0)
        if fee is None:
            return Decimal("0.0005")  # 최종 fallback: 0.05%
        return fee.taker_rate if method == "market" else fee.maker_rate

    @classmethod
    def _map_exchange_error(cls, exc: ExchangeError) -> AppError:
        """거래소 Provider 예외 → HTTP 응답용 AppError 변환.

        거래소 내부 에러 메시지는 로그에만 기록하고 클라이언트에 노출하지 않는다.
        """
        match exc:
            case ExchangeInsufficientBalanceError():
                return OrderErrors.insufficient_balance()
            case ExchangeUnavailableError():
                return OrderErrors.exchange_unavailable()
            case ExchangeRateLimitError() as e:
                return ExchangeErrors.rate_limited(e.exchange, e.retry_after_seconds)
            case ExchangeAuthError() as e:
                return ExchangeErrors.auth_failed(e.exchange)
            case ExchangePermissionError() as e:
                return ExchangeErrors.permission_denied(e.exchange, "TRADE")
            case ExchangeOrderError() as e:
                logger.warning("exchange_order_failed", extra={"detail": str(e)})
                return OrderErrors.exchange_order_failed()
            case _:
                logger.warning("exchange_order_failed_unknown", extra={"detail": str(exc)})
                return OrderErrors.exchange_order_failed()
