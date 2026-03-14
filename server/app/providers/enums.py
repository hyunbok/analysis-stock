"""거래소 추상화 계층 열거형 타입 정의."""
from __future__ import annotations

from enum import StrEnum


class ExchangeType(StrEnum):
    """지원 거래소 식별자."""

    UPBIT = "upbit"
    COINONE = "coinone"
    COINBASE = "coinbase"
    BINANCE = "binance"


class OrderSide(StrEnum):
    """주문 방향."""

    BUY = "buy"
    SELL = "sell"


class OrderMethod(StrEnum):
    """주문 방식."""

    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    """주문 상태 (TradeOrder.status와 동일한 값)."""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    PARTIAL = "partial"
    FAILED = "failed"


class ApiKeyPermission(StrEnum):
    """API 키 권한 종류 (거래소마다 표현 방식이 다르므로 정규화)."""

    VIEW_BALANCE = "view_balance"  # 잔고/자산 조회
    VIEW_ORDERS = "view_orders"    # 주문 내역 조회
    TRADE = "trade"                # 주문 생성/취소
    WITHDRAW = "withdraw"          # 출금 (경고 대상)


class CircuitState(StrEnum):
    """Circuit Breaker 상태."""

    CLOSED = "closed"        # 정상 동작
    OPEN = "open"            # 차단 중 (거래소 장애 감지)
    HALF_OPEN = "half_open"  # 복구 시도 중
