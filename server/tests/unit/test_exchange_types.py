"""거래소 공통 데이터 모델 단위 테스트."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.providers.enums import (
    ApiKeyPermission,
    ExchangeType,
    OrderMethod,
    OrderSide,
    OrderStatus,
)
from app.providers.exceptions import ExchangeInvalidSymbolError
from app.providers.types import (
    ApiKeyInfo,
    Balance,
    Candle,
    Order,
    OrderBook,
    OrderBookEntry,
    OrderResult,
    SymbolMapper,
    Ticker,
    TradingFee,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Ticker ────────────────────────────────────────────────────────────────────


def test_ticker_fields():
    ticker = Ticker(
        exchange=ExchangeType.UPBIT,
        symbol="BTC/KRW",
        market="KRW-BTC",
        price=Decimal("95000000"),
        open_price=Decimal("93000000"),
        high_price=Decimal("96000000"),
        low_price=Decimal("92000000"),
        volume=Decimal("100"),
        trade_value=Decimal("9500000000"),
        change_rate=Decimal("0.02"),
        timestamp=_now(),
    )
    assert ticker.exchange == ExchangeType.UPBIT
    assert ticker.price == Decimal("95000000")
    assert ticker.change_rate == Decimal("0.02")


def test_ticker_serialization():
    ticker = Ticker(
        exchange=ExchangeType.BINANCE,
        symbol="BTC/USDT",
        market="BTCUSDT",
        price=Decimal("65000"),
        open_price=Decimal("64000"),
        high_price=Decimal("66000"),
        low_price=Decimal("63500"),
        volume=Decimal("1000"),
        trade_value=Decimal("65000000"),
        change_rate=Decimal("0.015"),
        timestamp=_now(),
    )
    data = ticker.model_dump()
    assert data["exchange"] == "binance"
    assert data["symbol"] == "BTC/USDT"


# ── OrderBook ─────────────────────────────────────────────────────────────────


def test_orderbook_structure():
    asks = [OrderBookEntry(price=Decimal("65001"), quantity=Decimal("0.5"))]
    bids = [OrderBookEntry(price=Decimal("64999"), quantity=Decimal("0.5"))]
    ob = OrderBook(
        exchange=ExchangeType.BINANCE,
        symbol="BTC/USDT",
        market="BTCUSDT",
        asks=asks,
        bids=bids,
        timestamp=_now(),
    )
    assert len(ob.asks) == 1
    assert len(ob.bids) == 1
    assert ob.asks[0].price > ob.bids[0].price  # 매도 > 매수


# ── Candle ────────────────────────────────────────────────────────────────────


def test_candle_ohlcv():
    candle = Candle(
        exchange=ExchangeType.UPBIT,
        symbol="BTC/KRW",
        market="KRW-BTC",
        timeframe="1h",
        open=Decimal("95000000"),
        high=Decimal("96000000"),
        low=Decimal("94000000"),
        close=Decimal("95500000"),
        volume=Decimal("50"),
        timestamp=_now(),
    )
    assert candle.high >= candle.open
    assert candle.low <= candle.close


# ── Balance ───────────────────────────────────────────────────────────────────


def test_balance_total_property():
    balance = Balance(
        currency="BTC",
        available=Decimal("0.5"),
        locked=Decimal("0.1"),
    )
    assert balance.total == Decimal("0.6")


def test_balance_zero_locked():
    balance = Balance(currency="KRW", available=Decimal("1000000"), locked=Decimal("0"))
    assert balance.total == balance.available


# ── Order / OrderResult ───────────────────────────────────────────────────────


def test_order_market_buy():
    order = Order(
        market="KRW-BTC",
        side=OrderSide.BUY,
        method=OrderMethod.MARKET,
        quantity=Decimal("0.001"),
    )
    assert order.price is None
    assert order.side == OrderSide.BUY


def test_order_limit_sell():
    order = Order(
        market="KRW-BTC",
        side=OrderSide.SELL,
        method=OrderMethod.LIMIT,
        quantity=Decimal("0.001"),
        price=Decimal("95000000"),
    )
    assert order.price == Decimal("95000000")


def test_order_result_defaults():
    result = OrderResult(
        exchange_order_id="12345",
        market="KRW-BTC",
        side=OrderSide.BUY,
        method=OrderMethod.MARKET,
        status=OrderStatus.FILLED,
        quantity=Decimal("0.001"),
        created_at=_now(),
    )
    assert result.executed_quantity == Decimal("0")
    assert result.fee == Decimal("0")
    assert result.price is None


# ── TradingFee ────────────────────────────────────────────────────────────────


def test_trading_fee_fields():
    fee = TradingFee(
        exchange=ExchangeType.UPBIT,
        market="KRW-BTC",
        maker_fee=Decimal("0.0005"),
        taker_fee=Decimal("0.001"),
    )
    assert fee.maker_fee < fee.taker_fee


# ── ApiKeyInfo ────────────────────────────────────────────────────────────────


def test_api_key_info_valid():
    info = ApiKeyInfo(
        exchange=ExchangeType.UPBIT,
        permissions=[ApiKeyPermission.VIEW_BALANCE, ApiKeyPermission.TRADE],
        is_valid=True,
    )
    assert info.is_valid
    assert not info.has_withdraw_permission


def test_api_key_info_invalid():
    info = ApiKeyInfo(
        exchange=ExchangeType.COINONE,
        permissions=[],
        is_valid=False,
        error_message="Invalid key",
    )
    assert not info.is_valid
    assert info.error_message == "Invalid key"


# ── SymbolMapper ──────────────────────────────────────────────────────────────


def test_symbol_mapper_to_market_upbit():
    market = SymbolMapper.to_market(ExchangeType.UPBIT, "BTC/KRW")
    assert market == "KRW-BTC"


def test_symbol_mapper_to_market_binance():
    market = SymbolMapper.to_market(ExchangeType.BINANCE, "BTC/USDT")
    assert market == "BTCUSDT"


def test_symbol_mapper_to_symbol_upbit():
    symbol = SymbolMapper.to_symbol(ExchangeType.UPBIT, "KRW-BTC")
    assert symbol == "BTC/KRW"


def test_symbol_mapper_to_symbol_coinone():
    symbol = SymbolMapper.to_symbol(ExchangeType.COINONE, "BTC")
    assert symbol == "BTC/KRW"


def test_symbol_mapper_invalid_symbol():
    with pytest.raises(ExchangeInvalidSymbolError):
        SymbolMapper.to_market(ExchangeType.UPBIT, "DOGE/KRW")


def test_symbol_mapper_invalid_market():
    with pytest.raises(ExchangeInvalidSymbolError):
        SymbolMapper.to_symbol(ExchangeType.UPBIT, "UNKNOWN-MARKET")


def test_symbol_mapper_bidirectional_consistency():
    """to_market → to_symbol 왕복 일관성 검증."""
    # SymbolMapper._REVERSE 캐시 리셋
    SymbolMapper._REVERSE = {}

    for exchange, mappings in SymbolMapper._MAPS.items():
        for symbol, market in mappings.items():
            assert SymbolMapper.to_market(exchange, symbol) == market
            assert SymbolMapper.to_symbol(exchange, market) == symbol


# ── Enum StrEnum 직렬화 ────────────────────────────────────────────────────────


def test_exchange_type_is_str():
    assert ExchangeType.UPBIT == "upbit"
    assert ExchangeType.BINANCE == "binance"


def test_order_side_is_str():
    assert OrderSide.BUY == "buy"
    assert OrderSide.SELL == "sell"


def test_order_status_is_str():
    assert OrderStatus.FILLED == "filled"
    assert OrderStatus.CANCELLED == "cancelled"
