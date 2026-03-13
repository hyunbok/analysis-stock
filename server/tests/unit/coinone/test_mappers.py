"""CoinOne mappers.py 단위 테스트 — 응답 dict → 공통 모델 변환 검증 (10건)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.providers.coinone.mappers import (
    parse_balance,
    parse_cancel_result,
    parse_candle,
    parse_orderbook,
    parse_ticker,
    parse_trading_fee,
)


# ── 샘플 응답 데이터 ──────────────────────────────────────────────────────────

TICKER_SAMPLE = {
    "quote_currency": "KRW",
    "target_currency": "BTC",
    "timestamp": 1710000000000,
    "high": "96000000",
    "low": "92000000",
    "first": "93000000",
    "last": "95000000",
    "quote_volume": "11723000000",
    "target_volume": "123.4",
}

TICKER_ZERO_FIRST_SAMPLE = {
    "quote_currency": "KRW",
    "target_currency": "BTC",
    "timestamp": 1710000000000,
    "high": "96000000",
    "low": "92000000",
    "first": "0",
    "last": "95000000",
    "quote_volume": "11723000000",
    "target_volume": "123.4",
}

ORDERBOOK_SAMPLE = {
    "quote_currency": "KRW",
    "target_currency": "BTC",
    "timestamp": 1710000000000,
    "asks": [
        {"price": "95200000", "qty": "0.3"},
        {"price": "95100000", "qty": "0.5"},
        {"price": "95300000", "qty": "0.2"},
    ],
    "bids": [
        {"price": "94900000", "qty": "0.3"},
        {"price": "94800000", "qty": "0.4"},
        {"price": "94700000", "qty": "0.5"},
    ],
}

CANDLE_SAMPLE = {
    "timestamp": 1710000000000,
    "open": "93000000",
    "high": "96000000",
    "low": "92000000",
    "close": "95000000",
    "target_volume": "123.4",
    "quote_volume": "11723000000",
}

ORDER_RESULT_SAMPLE = {
    "order_id": "test-order-uuid",
    "target_currency": "BTC",
    "quote_currency": "KRW",
    "side": "BUY",
    "type": "LIMIT",
    "price": "95000000",
    "qty": "0.001",
}

CANCEL_RESULT_SAMPLE = {
    "order_id": "cancel-order-uuid",
    "target_currency": "BTC",
    "quote_currency": "KRW",
    "side": "BUY",
    "price": "95000000",
    "qty": "0.001",
    "remain_qty": "0.001",
    "traded_qty": "0",
    "canceled_qty": "0.001",
    "fee": "0",
    "avg_price": "0",
    "canceled_at": 1710000000000,
}

CANCEL_PARTIAL_RESULT_SAMPLE = {
    "order_id": "partial-order-uuid",
    "target_currency": "BTC",
    "quote_currency": "KRW",
    "side": "SELL",
    "price": "95000000",
    "qty": "0.002",
    "remain_qty": "0.001",
    "traded_qty": "0.001",
    "canceled_qty": "0.001",
    "fee": "19",
    "avg_price": "95000000",
    "canceled_at": 1710000000000,
}

BALANCE_SAMPLE = {
    "currency": "KRW",
    "available": "10000000",
    "limit": "0",
}

BALANCE_BTC_SAMPLE = {
    "currency": "btc",
    "available": "0.1",
    "limit": "0.01",
}

TRADING_FEE_SAMPLE = {
    "maker_fee": "0.0002",
    "taker_fee": "0.0002",
}


# ── TC1: parse_ticker ─────────────────────────────────────────────────────────


def test_parse_ticker() -> None:
    """REST ticker 응답 → Ticker 변환."""
    from app.providers.enums import ExchangeType

    ticker = parse_ticker(TICKER_SAMPLE)
    assert ticker.exchange == ExchangeType.COINONE
    assert ticker.market == "BTC"
    assert ticker.symbol == "BTC/KRW"
    assert ticker.price == Decimal("95000000")
    assert ticker.open_price == Decimal("93000000")
    assert ticker.high_price == Decimal("96000000")
    assert ticker.low_price == Decimal("92000000")
    assert ticker.volume == Decimal("123.4")
    assert ticker.trade_value == Decimal("11723000000")
    assert ticker.timestamp.tzinfo == timezone.utc


# ── TC2: parse_ticker change_rate 계산 ────────────────────────────────────────


def test_parse_ticker_change_rate() -> None:
    """change_rate 계산 (last-first)/first + first=0 방어."""
    ticker = parse_ticker(TICKER_SAMPLE)
    # (95000000 - 93000000) / 93000000 ≈ 0.0215...
    expected = (Decimal("95000000") - Decimal("93000000")) / Decimal("93000000")
    assert ticker.change_rate == expected

    # first=0 엣지케이스
    ticker_zero = parse_ticker(TICKER_ZERO_FIRST_SAMPLE)
    assert ticker_zero.change_rate == Decimal("0")


# ── TC3: parse_orderbook ──────────────────────────────────────────────────────


def test_parse_orderbook() -> None:
    """REST orderbook 응답 → OrderBook 변환 (asks 오름차순, bids 내림차순)."""
    from app.providers.enums import ExchangeType

    ob = parse_orderbook(ORDERBOOK_SAMPLE)
    assert ob.exchange == ExchangeType.COINONE
    assert ob.market == "BTC"
    assert ob.symbol == "BTC/KRW"
    # asks: 오름차순
    assert ob.asks[0].price < ob.asks[1].price
    assert ob.asks[0].price < ob.asks[2].price
    # bids: 내림차순
    assert ob.bids[0].price > ob.bids[1].price
    assert ob.bids[0].price > ob.bids[2].price
    assert ob.timestamp.tzinfo == timezone.utc


# ── TC4: parse_orderbook depth 파라미터 ───────────────────────────────────────


def test_parse_orderbook_depth() -> None:
    """depth 파라미터 적용 — depth=2이면 asks/bids 각 2개."""
    ob = parse_orderbook(ORDERBOOK_SAMPLE, depth=2)
    assert len(ob.asks) == 2
    assert len(ob.bids) == 2


# ── TC5: parse_candle ─────────────────────────────────────────────────────────


def test_parse_candle() -> None:
    """REST candle 응답 → Candle 변환."""
    from app.providers.enums import ExchangeType

    candle = parse_candle(CANDLE_SAMPLE, target_currency="BTC", timeframe="1h")
    assert candle.exchange == ExchangeType.COINONE
    assert candle.market == "BTC"
    assert candle.symbol == "BTC/KRW"
    assert candle.timeframe == "1h"
    assert candle.open == Decimal("93000000")
    assert candle.high == Decimal("96000000")
    assert candle.low == Decimal("92000000")
    assert candle.close == Decimal("95000000")
    assert candle.volume == Decimal("123.4")
    # 1710000000000 ms epoch = 2024-03-09T16:00:00 UTC
    assert candle.timestamp == datetime.fromtimestamp(1710000000, tz=timezone.utc)


# ── TC6: parse_order_result ───────────────────────────────────────────────────


def test_parse_order_result() -> None:
    """주문 결과 변환."""
    from app.providers.enums import OrderMethod, OrderSide, OrderStatus

    from app.providers.coinone.mappers import parse_order_result

    order = parse_order_result(ORDER_RESULT_SAMPLE)
    assert order.exchange_order_id == "test-order-uuid"
    assert order.market == "BTC"
    assert order.side == OrderSide.BUY
    assert order.method == OrderMethod.LIMIT
    assert order.status == OrderStatus.PENDING
    assert order.price == Decimal("95000000")
    assert order.quantity == Decimal("0.001")


# ── TC7: parse_cancel_result ──────────────────────────────────────────────────


def test_parse_cancel_result() -> None:
    """취소 결과 변환 — 미체결 취소 → CANCELLED."""
    from app.providers.enums import OrderSide, OrderStatus

    result = parse_cancel_result(CANCEL_RESULT_SAMPLE)
    assert result.exchange_order_id == "cancel-order-uuid"
    assert result.side == OrderSide.BUY
    assert result.status == OrderStatus.CANCELLED
    assert result.quantity == Decimal("0.001")
    assert result.executed_quantity == Decimal("0")


def test_parse_cancel_result_partial() -> None:
    """부분 체결 후 취소 → PARTIAL."""
    from app.providers.enums import OrderStatus

    result = parse_cancel_result(CANCEL_PARTIAL_RESULT_SAMPLE)
    assert result.status == OrderStatus.PARTIAL
    assert result.executed_quantity == Decimal("0.001")
    assert result.fee == Decimal("19")


# ── TC8: parse_balance ────────────────────────────────────────────────────────


def test_parse_balance() -> None:
    """잔고 변환 — limit → locked."""
    balance = parse_balance(BALANCE_SAMPLE)
    assert balance.currency == "KRW"
    assert balance.available == Decimal("10000000")
    assert balance.locked == Decimal("0")

    # 소문자 currency → 대문자 변환
    balance_btc = parse_balance(BALANCE_BTC_SAMPLE)
    assert balance_btc.currency == "BTC"
    assert balance_btc.available == Decimal("0.1")
    assert balance_btc.locked == Decimal("0.01")


# ── TC9: parse_trading_fee ────────────────────────────────────────────────────


def test_parse_trading_fee() -> None:
    """수수료 변환."""
    from app.providers.enums import ExchangeType

    fee = parse_trading_fee(TRADING_FEE_SAMPLE, market="BTC")
    assert fee.exchange == ExchangeType.COINONE
    assert fee.market == "BTC"
    assert fee.maker_fee == Decimal("0.0002")
    assert fee.taker_fee == Decimal("0.0002")


# ── TC10: Decimal 정밀도 ──────────────────────────────────────────────────────


def test_decimal_precision() -> None:
    """float 미사용 — 모든 가격/수량이 Decimal 타입."""
    ticker = parse_ticker(TICKER_SAMPLE)
    assert isinstance(ticker.price, Decimal)
    assert isinstance(ticker.volume, Decimal)
    assert isinstance(ticker.change_rate, Decimal)

    ob = parse_orderbook(ORDERBOOK_SAMPLE)
    assert isinstance(ob.asks[0].price, Decimal)
    assert isinstance(ob.bids[0].quantity, Decimal)

    candle = parse_candle(CANDLE_SAMPLE, target_currency="BTC", timeframe="1h")
    assert isinstance(candle.open, Decimal)
    assert isinstance(candle.volume, Decimal)

    balance = parse_balance(BALANCE_SAMPLE)
    assert isinstance(balance.available, Decimal)
    assert isinstance(balance.locked, Decimal)
