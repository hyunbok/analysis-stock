"""Upbit mappers.py 단위 테스트 — 응답 dict → 공통 모델 변환 검증."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.providers.upbit.mappers import (
    parse_balance,
    parse_candle,
    parse_order_result,
    parse_orderbook,
    parse_ticker,
)


# ── 샘플 응답 데이터 ──────────────────────────────────────────────────────────

TICKER_SAMPLE = {
    "market": "KRW-BTC",
    "trade_price": 95000000.0,
    "opening_price": 93000000.0,
    "high_price": 96000000.0,
    "low_price": 92000000.0,
    "acc_trade_volume_24h": 123.4,
    "acc_trade_price_24h": 11723000000.0,
    "signed_change_rate": 0.0215,
    "trade_timestamp": 1710000000000,
}

ORDERBOOK_SAMPLE = {
    "market": "KRW-BTC",
    "timestamp": 1710000000000,
    "orderbook_units": [
        {"ask_price": 95100000, "bid_price": 94900000, "ask_size": 0.5, "bid_size": 0.3},
        {"ask_price": 95200000, "bid_price": 94800000, "ask_size": 0.3, "bid_size": 0.4},
        {"ask_price": 95300000, "bid_price": 94700000, "ask_size": 0.2, "bid_size": 0.5},
    ],
}

CANDLE_SAMPLE = {
    "market": "KRW-BTC",
    "candle_date_time_utc": "2024-03-10T00:00:00",
    "opening_price": 93000000.0,
    "high_price": 96000000.0,
    "low_price": 92000000.0,
    "trade_price": 95000000.0,
    "candle_acc_trade_volume": 123.4,
}

ORDER_LIMIT_BUY_SAMPLE = {
    "uuid": "test-order-uuid",
    "market": "KRW-BTC",
    "side": "bid",
    "ord_type": "limit",
    "state": "wait",
    "volume": "0.001",
    "executed_volume": "0.0",
    "price": "95000000",
    "avg_buy_price": "0",
    "paid_fee": "0",
    "created_at": "2024-03-10T10:00:00+09:00",
}

ORDER_MARKET_BUY_SAMPLE = {
    "uuid": "market-buy-uuid",
    "market": "KRW-BTC",
    "side": "bid",
    "ord_type": "price",
    "state": "done",
    "volume": None,
    "executed_volume": "0.001",
    "price": "95000",
    "avg_buy_price": "95000000",
    "paid_fee": "47.5",
    "created_at": "2024-03-10T10:00:00+09:00",
}

ORDER_MARKET_SELL_SAMPLE = {
    "uuid": "market-sell-uuid",
    "market": "KRW-BTC",
    "side": "ask",
    "ord_type": "market",
    "state": "done",
    "volume": "0.001",
    "executed_volume": "0.001",
    "price": None,
    "avg_buy_price": "95000000",
    "paid_fee": "47.5",
    "created_at": "2024-03-10T10:00:00+09:00",
}

BALANCE_SAMPLE = {
    "currency": "KRW",
    "balance": "10000000.0",
    "locked": "0.0",
}

WS_TICKER_SAMPLE = {
    "type": "ticker",
    "code": "KRW-BTC",
    "trade_price": 95000000.0,
    "opening_price": 93000000.0,
    "high_price": 96000000.0,
    "low_price": 92000000.0,
    "acc_trade_volume_24h": 123.4,
    "acc_trade_price_24h": 11723000000.0,
    "signed_change_rate": 0.0215,
    "trade_timestamp": 1710000000000,
}


# ── TC1: parse_ticker ─────────────────────────────────────────────────────────


def test_parse_ticker() -> None:
    """REST ticker 응답 → Ticker 변환."""
    ticker = parse_ticker(TICKER_SAMPLE)
    assert ticker.market == "KRW-BTC"
    assert ticker.symbol == "BTC/KRW"
    assert ticker.price == Decimal("95000000.0")
    assert ticker.open_price == Decimal("93000000.0")
    assert ticker.high_price == Decimal("96000000.0")
    assert ticker.low_price == Decimal("92000000.0")
    assert ticker.volume == Decimal("123.4")
    assert ticker.change_rate == Decimal("0.0215")
    assert ticker.timestamp.tzinfo == timezone.utc


# ── TC2: parse_orderbook ──────────────────────────────────────────────────────


def test_parse_orderbook() -> None:
    """REST orderbook 응답 → OrderBook 변환 (asks 오름차순, bids 내림차순)."""
    ob = parse_orderbook(ORDERBOOK_SAMPLE)
    assert ob.market == "KRW-BTC"
    assert ob.symbol == "BTC/KRW"
    # asks: 오름차순
    assert ob.asks[0].price < ob.asks[1].price
    # bids: 내림차순
    assert ob.bids[0].price > ob.bids[1].price
    assert ob.asks[0].quantity == Decimal("0.5")
    assert ob.bids[0].quantity == Decimal("0.3")


def test_parse_orderbook_depth() -> None:
    """depth 파라미터 적용 — depth=2이면 asks/bids 각 2개."""
    ob = parse_orderbook(ORDERBOOK_SAMPLE, depth=2)
    assert len(ob.asks) == 2
    assert len(ob.bids) == 2


# ── TC3: parse_candle ─────────────────────────────────────────────────────────


def test_parse_candle() -> None:
    """REST candle 응답 → Candle 변환."""
    candle = parse_candle(CANDLE_SAMPLE, market="KRW-BTC", timeframe="1d")
    assert candle.market == "KRW-BTC"
    assert candle.symbol == "BTC/KRW"
    assert candle.timeframe == "1d"
    assert candle.open == Decimal("93000000.0")
    assert candle.high == Decimal("96000000.0")
    assert candle.low == Decimal("92000000.0")
    assert candle.close == Decimal("95000000.0")
    assert candle.volume == Decimal("123.4")
    assert candle.timestamp == datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)


# ── TC4: parse_order_result ───────────────────────────────────────────────────


def test_parse_order_result_limit() -> None:
    """지정가 주문 결과 변환."""
    from app.providers.enums import OrderMethod, OrderSide, OrderStatus

    result = parse_order_result(ORDER_LIMIT_BUY_SAMPLE)
    assert result.exchange_order_id == "test-order-uuid"
    assert result.market == "KRW-BTC"
    assert result.side == OrderSide.BUY
    assert result.method == OrderMethod.LIMIT
    assert result.status == OrderStatus.OPEN  # "wait" → OPEN (거래소 접수 완료, 체결 대기)
    assert result.price == Decimal("95000000")


def test_parse_order_result_market_buy() -> None:
    """시장가 매수 결과 변환 (ord_type=price)."""
    from app.providers.enums import OrderMethod, OrderSide, OrderStatus

    result = parse_order_result(ORDER_MARKET_BUY_SAMPLE)
    assert result.side == OrderSide.BUY
    assert result.method == OrderMethod.MARKET
    assert result.status == OrderStatus.FILLED
    assert result.executed_quantity == Decimal("0.001")
    assert result.fee == Decimal("47.5")


def test_parse_order_result_market_sell() -> None:
    """시장가 매도 결과 변환 (ord_type=market)."""
    from app.providers.enums import OrderMethod, OrderSide, OrderStatus

    result = parse_order_result(ORDER_MARKET_SELL_SAMPLE)
    assert result.side == OrderSide.SELL
    assert result.method == OrderMethod.MARKET
    assert result.status == OrderStatus.FILLED


# ── TC5: parse_balance ────────────────────────────────────────────────────────


def test_parse_balance() -> None:
    """잔고 변환."""
    balance = parse_balance(BALANCE_SAMPLE)
    assert balance.currency == "KRW"
    assert balance.available == Decimal("10000000.0")
    assert balance.locked == Decimal("0.0")
    assert balance.total == Decimal("10000000.0")


# ── TC6: WS 특수 케이스 ───────────────────────────────────────────────────────


def test_ws_ticker_code_field() -> None:
    """WS ticker의 'code' 필드 → 'market'으로 올바르게 매핑."""
    ticker = parse_ticker(WS_TICKER_SAMPLE)
    assert ticker.market == "KRW-BTC"  # 'code' 필드를 market으로 사용
    assert ticker.symbol == "BTC/KRW"


def test_decimal_precision() -> None:
    """float 미사용 — 모든 가격/수량이 Decimal 타입."""
    ticker = parse_ticker(TICKER_SAMPLE)
    assert isinstance(ticker.price, Decimal)
    assert isinstance(ticker.volume, Decimal)
    assert isinstance(ticker.change_rate, Decimal)

    ob = parse_orderbook(ORDERBOOK_SAMPLE)
    assert isinstance(ob.asks[0].price, Decimal)
    assert isinstance(ob.bids[0].quantity, Decimal)

    candle = parse_candle(CANDLE_SAMPLE, market="KRW-BTC", timeframe="1d")
    assert isinstance(candle.open, Decimal)
    assert isinstance(candle.volume, Decimal)
