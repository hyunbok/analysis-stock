"""Upbit API 응답 dict → 공통 Pydantic 모델 변환 순수함수 모음.

모든 함수:
- 상태(state)를 갖지 않음 (순수함수)
- 입력: Upbit API 응답 dict
- 출력: providers/types.py의 공통 모델
- 파싱 실패 시: ExchangeDataError raise
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ..enums import ExchangeType, OrderMethod, OrderSide
from ..exceptions import ExchangeDataError
from ..types import Balance, Candle, OrderBook, OrderBookEntry, OrderResult, Ticker
from .constants import UPBIT_ORDER_STATUS_MAP


def _market_to_symbol(market: str) -> str:
    """Upbit 마켓 코드 → 정규화 심볼.

    Examples:
        "KRW-BTC" → "BTC/KRW"
        "BTC-ETH" → "ETH/BTC"
    """
    parts = market.split("-", 1)
    if len(parts) == 2:
        return f"{parts[1]}/{parts[0]}"
    return market


def parse_ticker(data: dict) -> Ticker:
    """Upbit REST /v1/ticker 또는 WS ticker 응답 → Ticker 변환.

    REST 응답: 배열의 단일 원소 dict.
    WS 응답: type="ticker" 메시지 dict (필드명 동일, 일부 생략).

    Upbit 필드 매핑:
      trade_price           → price
      opening_price         → open_price
      high_price            → high_price
      low_price             → low_price
      acc_trade_volume_24h  → volume
      acc_trade_price_24h   → trade_value
      signed_change_rate    → change_rate
      trade_timestamp (ms)  → timestamp (UTC datetime)
      code / market         → market
    """
    try:
        market = data.get("code") or data.get("market", "")
        ts_ms = int(data["trade_timestamp"])
        return Ticker(
            exchange=ExchangeType.UPBIT,
            symbol=_market_to_symbol(market),
            market=market,
            price=Decimal(str(data["trade_price"])),
            open_price=Decimal(str(data["opening_price"])),
            high_price=Decimal(str(data["high_price"])),
            low_price=Decimal(str(data["low_price"])),
            volume=Decimal(str(data["acc_trade_volume_24h"])),
            trade_value=Decimal(str(data["acc_trade_price_24h"])),
            change_rate=Decimal(str(data["signed_change_rate"])),
            timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("upbit", f"Failed to parse ticker: {exc}") from exc


def parse_orderbook(data: dict, depth: int = 10) -> OrderBook:
    """Upbit REST /v1/orderbook 또는 WS orderbook 응답 → OrderBook 변환.

    orderbook_units[:depth]:
      ask_price, ask_size → asks (오름차순)
      bid_price, bid_size → bids (내림차순)
    """
    try:
        market = data.get("code") or data.get("market", "")
        units = data.get("orderbook_units", [])[:depth]
        ts_ms = int(data["timestamp"])

        asks = sorted(
            [
                OrderBookEntry(
                    price=Decimal(str(u["ask_price"])),
                    quantity=Decimal(str(u["ask_size"])),
                )
                for u in units
            ],
            key=lambda e: e.price,
        )
        bids = sorted(
            [
                OrderBookEntry(
                    price=Decimal(str(u["bid_price"])),
                    quantity=Decimal(str(u["bid_size"])),
                )
                for u in units
            ],
            key=lambda e: e.price,
            reverse=True,
        )
        return OrderBook(
            exchange=ExchangeType.UPBIT,
            symbol=_market_to_symbol(market),
            market=market,
            asks=asks,
            bids=bids,
            timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("upbit", f"Failed to parse orderbook: {exc}") from exc


def parse_candle(data: dict, market: str, timeframe: str) -> Candle:
    """Upbit REST /v1/candles/* 단일 캔들 dict → Candle 변환.

    Upbit 필드 매핑:
      candle_date_time_utc  → timestamp (fromisoformat + tzinfo=UTC)
      opening_price         → open
      high_price            → high
      low_price             → low
      trade_price           → close
      candle_acc_trade_volume → volume
    """
    try:
        dt_str = data["candle_date_time_utc"]
        # "2024-03-10T00:00:00" 형식 — timezone 정보 없으므로 UTC로 명시
        ts = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
        return Candle(
            exchange=ExchangeType.UPBIT,
            symbol=_market_to_symbol(market),
            market=market,
            timeframe=timeframe,
            open=Decimal(str(data["opening_price"])),
            high=Decimal(str(data["high_price"])),
            low=Decimal(str(data["low_price"])),
            close=Decimal(str(data["trade_price"])),
            volume=Decimal(str(data["candle_acc_trade_volume"])),
            timestamp=ts,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("upbit", f"Failed to parse candle: {exc}") from exc


def parse_order_result(data: dict) -> OrderResult:
    """Upbit REST /v1/orders POST/DELETE 응답 → OrderResult 변환.

    Upbit 필드 매핑:
      uuid              → exchange_order_id
      state             → status (UPBIT_ORDER_STATUS_MAP)
      volume            → quantity
      executed_volume   → executed_quantity
      price             → price
      avg_buy_price     → avg_executed_price (체결 시)
      paid_fee          → fee
      created_at        → created_at (ISO8601 with TZ)
    """
    try:
        side_raw = data.get("side", "bid")
        side = OrderSide.BUY if side_raw == "bid" else OrderSide.SELL

        ord_type = data.get("ord_type", "limit")
        if ord_type == "limit":
            method = OrderMethod.LIMIT
        else:
            method = OrderMethod.MARKET

        status = UPBIT_ORDER_STATUS_MAP.get(data.get("state", "wait"), None)
        if status is None:
            raise ExchangeDataError("upbit", f"Unknown order state: {data.get('state')}")

        price_raw = data.get("price")
        price = Decimal(str(price_raw)) if price_raw is not None else None

        avg_raw = data.get("avg_buy_price")
        avg_dec = Decimal(str(avg_raw)) if avg_raw is not None else Decimal("0")
        avg_price = avg_dec if avg_dec > 0 else None

        volume_raw = data.get("volume") or data.get("executed_volume", "0")
        quantity = Decimal(str(volume_raw)) if volume_raw else Decimal("0")

        exec_vol_raw = data.get("executed_volume", "0")
        exec_quantity = Decimal(str(exec_vol_raw)) if exec_vol_raw else Decimal("0")

        fee_raw = data.get("paid_fee", "0")
        fee = Decimal(str(fee_raw)) if fee_raw else Decimal("0")

        created_at = datetime.fromisoformat(data["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        return OrderResult(
            exchange_order_id=data["uuid"],
            market=data["market"],
            side=side,
            method=method,
            status=status,
            quantity=quantity,
            executed_quantity=exec_quantity,
            price=price,
            avg_executed_price=avg_price,
            fee=fee,
            fee_currency=data["market"].split("-")[0] if "-" in data["market"] else "KRW",
            created_at=created_at,
        )
    except ExchangeDataError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("upbit", f"Failed to parse order result: {exc}") from exc


def parse_balance(data: dict) -> Balance:
    """Upbit REST /v1/accounts 단일 계좌 dict → Balance 변환.

    Upbit 필드 매핑:
      currency → currency
      balance  → available
      locked   → locked
    """
    try:
        return Balance(
            currency=data["currency"],
            available=Decimal(str(data["balance"])),
            locked=Decimal(str(data["locked"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("upbit", f"Failed to parse balance: {exc}") from exc
