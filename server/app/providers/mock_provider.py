"""Mock Exchange Provider — 테스트/개발 환경용 시뮬레이션 구현체."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from .base_impl import BaseExchangeProvider
from .enums import ApiKeyPermission, ExchangeType, OrderMethod, OrderSide, OrderStatus
from .exceptions import ExchangeOrderError
from .types import (
    ApiKeyInfo,
    Balance,
    Candle,
    Order,
    OrderBook,
    OrderBookEntry,
    OrderResult,
    Ticker,
    TradingFee,
)

logger = logging.getLogger(__name__)


class MockOrderScenario(StrEnum):
    """MockExchangeProvider 주문 시뮬레이션 시나리오."""

    IMMEDIATE_FILL = "immediate_fill"  # 시장가처럼 즉시 완전 체결 (기본값)
    OPEN = "open"                      # 지정가처럼 OPEN 상태 유지
    PARTIAL_FILL = "partial_fill"      # 50% 부분 체결 후 PARTIAL 상태
    FAIL = "fail"                      # 거래소 거부 (잔고 부족 시뮬레이션)

# ── 시뮬레이션용 정적 데이터 ──────────────────────────────────────────────────

_MOCK_PRICES: dict[str, Decimal] = {
    "KRW-BTC": Decimal("95000000"),
    "KRW-ETH": Decimal("5000000"),
    "KRW-XRP": Decimal("800"),
    "btc": Decimal("95000000"),
    "eth": Decimal("5000000"),
    "BTC-USDT": Decimal("65000"),
    "ETH-USDT": Decimal("3400"),
    "BTCUSDT": Decimal("65000"),
    "ETHUSDT": Decimal("3400"),
}

_DEFAULT_PRICE = Decimal("10000")


class MockExchangeProvider(BaseExchangeProvider):
    """모든 거래소 타입에 사용 가능한 Mock Provider.

    - 실제 네트워크 호출 없이 시뮬레이션 데이터 반환
    - Factory.register_defaults()에 의해 모든 거래소에 기본 등록
    - 테스트/개발 환경에서 전체 Provider 흐름 검증 가능

    시나리오 변경:
        provider.set_scenario(MockOrderScenario.PARTIAL_FILL)
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._scenario: MockOrderScenario = MockOrderScenario.IMMEDIATE_FILL
        # 주문 저장소: exchange_order_id → OrderResult (get_order 조회용)
        self._orders: dict[str, OrderResult] = {}
        self._custom_balances: list[Balance] | None = None  # E2E 테스트용 동적 잔고

    def set_scenario(self, scenario: MockOrderScenario) -> None:
        """테스트용 주문 시나리오 설정."""
        self._scenario = scenario

    def set_balance(self, balances: list[Balance]) -> None:
        """E2E 테스트용 잔고 동적 설정."""
        self._custom_balances = balances

    def reset_orders(self) -> None:
        """테스트 간 전체 상태 초기화."""
        self._orders.clear()
        self._scenario = MockOrderScenario.IMMEDIATE_FILL
        self._custom_balances = None

    def _now(self) -> datetime:
        return datetime.now(tz=timezone.utc)

    def _price(self, market: str) -> Decimal:
        return _MOCK_PRICES.get(market, _DEFAULT_PRICE)

    def _symbol(self, market: str) -> str:
        """Mock 심볼 — market 코드를 그대로 사용."""
        return market

    # ── REST: 시세 / 호가 / 캔들 ────────────────────────────────────────────

    async def get_ticker(self, market: str) -> Ticker:
        price = self._price(market)
        return Ticker(
            exchange=self._exchange_type,
            symbol=self._symbol(market),
            market=market,
            price=price,
            open_price=price * Decimal("0.98"),
            high_price=price * Decimal("1.02"),
            low_price=price * Decimal("0.97"),
            volume=Decimal("100"),
            trade_value=price * Decimal("100"),
            change_rate=Decimal("0.02"),
            timestamp=self._now(),
        )

    async def get_orderbook(self, market: str, depth: int = 10) -> OrderBook:
        price = self._price(market)
        asks = [
            OrderBookEntry(
                price=price * (Decimal("1") + Decimal("0.001") * i),
                quantity=Decimal("0.1"),
            )
            for i in range(1, depth + 1)
        ]
        bids = [
            OrderBookEntry(
                price=price * (Decimal("1") - Decimal("0.001") * i),
                quantity=Decimal("0.1"),
            )
            for i in range(1, depth + 1)
        ]
        return OrderBook(
            exchange=self._exchange_type,
            symbol=self._symbol(market),
            market=market,
            asks=asks,
            bids=bids,
            timestamp=self._now(),
        )

    async def get_candles(
        self, market: str, timeframe: str, count: int = 200
    ) -> list[Candle]:
        price = self._price(market)
        now = self._now()
        candles = []
        for _ in range(count):
            candles.append(
                Candle(
                    exchange=self._exchange_type,
                    symbol=self._symbol(market),
                    market=market,
                    timeframe=timeframe,
                    open=price,
                    high=price * Decimal("1.01"),
                    low=price * Decimal("0.99"),
                    close=price,
                    volume=Decimal("10"),
                    timestamp=now.replace(
                        second=0, microsecond=0
                    ),
                )
            )
        return candles

    # ── REST: 주문 ───────────────────────────────────────────────────────────

    async def place_order(self, order: Order) -> OrderResult:
        """시나리오별 주문 결과 반환.

        - IMMEDIATE_FILL: 시장가처럼 즉시 완전 체결 (FILLED)
        - OPEN: 지정가처럼 거래소 접수 완료, 체결 대기 (OPEN)
        - PARTIAL_FILL: 주문 수량의 50% 부분 체결 (PARTIAL)
        - FAIL: ExchangeOrderError raise (잔고 부족 시뮬레이션)
        """
        if self._scenario == MockOrderScenario.FAIL:
            raise ExchangeOrderError(
                self._exchange_type.value,
                "Mock: insufficient balance (scenario=FAIL)",
            )

        price = self._price(order.market)
        exec_price = order.price if order.price else price
        fee_currency = "KRW" if "KRW" in order.market else "USDT"
        now = self._now()

        if self._scenario == MockOrderScenario.OPEN:
            result = OrderResult(
                exchange_order_id=str(uuid.uuid4()),
                market=order.market,
                side=order.side,
                method=order.method,
                status=OrderStatus.OPEN,
                quantity=order.quantity,
                executed_quantity=Decimal("0"),
                price=order.price,
                avg_executed_price=None,
                fee=Decimal("0"),
                fee_currency=fee_currency,
                created_at=now,
                executed_at=None,
            )
        elif self._scenario == MockOrderScenario.PARTIAL_FILL:
            partial_qty = order.quantity * Decimal("0.5")
            result = OrderResult(
                exchange_order_id=str(uuid.uuid4()),
                market=order.market,
                side=order.side,
                method=order.method,
                status=OrderStatus.PARTIAL,
                quantity=order.quantity,
                executed_quantity=partial_qty,
                price=order.price,
                avg_executed_price=exec_price,
                fee=exec_price * partial_qty * Decimal("0.001"),
                fee_currency=fee_currency,
                created_at=now,
                executed_at=now,
            )
        else:
            # IMMEDIATE_FILL (기본값)
            result = OrderResult(
                exchange_order_id=str(uuid.uuid4()),
                market=order.market,
                side=order.side,
                method=order.method,
                status=OrderStatus.FILLED,
                quantity=order.quantity,
                executed_quantity=order.quantity,
                price=order.price,
                avg_executed_price=exec_price,
                fee=exec_price * order.quantity * Decimal("0.001"),
                fee_currency=fee_currency,
                created_at=now,
                executed_at=now,
            )

        # 주문 저장 (get_order 조회용)
        self._orders[result.exchange_order_id] = result
        return result

    async def cancel_order(self, market: str, exchange_order_id: str) -> bool:
        """주문 취소 — 저장된 주문 상태를 CANCELLED로 변경."""
        if exchange_order_id in self._orders:
            order = self._orders[exchange_order_id]
            # 이미 체결된 주문은 취소 불가 → False 반환
            if order.status == OrderStatus.FILLED:
                return False
            cancelled = order.model_copy(
                update={"status": OrderStatus.CANCELLED}
            )
            self._orders[exchange_order_id] = cancelled
        return True

    async def get_order(self, market: str, exchange_order_id: str) -> OrderResult:
        """저장된 주문 상태 반환."""
        if exchange_order_id not in self._orders:
            raise ExchangeOrderError(
                self._exchange_type.value,
                f"Mock: order not found: {exchange_order_id}",
            )
        return self._orders[exchange_order_id]

    # ── REST: 잔고 / 수수료 / API 키 ────────────────────────────────────────

    async def get_balance(self) -> list[Balance]:
        if self._custom_balances is not None:
            return self._custom_balances
        return [
            Balance(
                currency="KRW",
                available=Decimal("10000000"),
                locked=Decimal("0"),
            ),
            Balance(
                currency="BTC",
                available=Decimal("0.1"),
                locked=Decimal("0"),
            ),
        ]

    async def get_trading_fee(self, market: str) -> TradingFee:
        return TradingFee(
            exchange=self._exchange_type,
            market=market,
            maker_fee=Decimal("0.0005"),
            taker_fee=Decimal("0.001"),
        )

    async def verify_api_key(self) -> ApiKeyInfo:
        return ApiKeyInfo(
            exchange=self._exchange_type,
            permissions=[
                ApiKeyPermission.VIEW_BALANCE,
                ApiKeyPermission.VIEW_ORDERS,
                ApiKeyPermission.TRADE,
            ],
            is_valid=True,
            has_withdraw_permission=False,
        )

    # ── WebSocket ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._ws_connected = True
        logger.debug("MockProvider[%s] WebSocket connected", self._exchange_type)

    async def disconnect(self) -> None:
        self._ws_connected = False
        logger.debug("MockProvider[%s] WebSocket disconnected", self._exchange_type)

    async def subscribe_ticker(
        self,
        markets: list[str],
        callback: Callable[[Ticker], Awaitable[None]],
    ) -> None:
        """Mock: 즉시 1회 시세 데이터 전달 후 종료."""
        for market in markets:
            ticker = await self.get_ticker(market)
            await callback(ticker)

    async def subscribe_orderbook(
        self,
        markets: list[str],
        callback: Callable[[OrderBook], Awaitable[None]],
    ) -> None:
        """Mock: 즉시 1회 호가 데이터 전달 후 종료."""
        for market in markets:
            orderbook = await self.get_orderbook(market)
            await callback(orderbook)

    async def unsubscribe(self, markets: list[str] | None = None) -> None:
        logger.debug(
            "MockProvider[%s] unsubscribed from %s",
            self._exchange_type,
            markets or "all",
        )
