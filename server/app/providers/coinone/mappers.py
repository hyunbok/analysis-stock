"""CoinOne API 응답 dict → 공통 Pydantic 모델 변환 순수함수 모음.

모든 함수:
- 상태(state)를 갖지 않음 (순수함수)
- 입력: CoinOne API 응답 dict
- 출력: providers/types.py의 공통 모델
- 파싱 실패 시: ExchangeDataError raise
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ..enums import ExchangeType, OrderMethod, OrderSide, OrderStatus
from ..exceptions import ExchangeDataError
from ..types import Balance, Candle, OrderBook, OrderBookEntry, OrderResult, Ticker, TradingFee

# v1 범위에서 KRW 마켓 고정
QUOTE_CURRENCY = "KRW"


def _to_symbol(quote: str, target: str) -> str:
    """CoinOne API 응답 (quote, target) → 정규화 심볼.

    Args:
        quote: 기준 통화 e.g. "KRW"
        target: 대상 통화 e.g. "BTC"

    Returns:
        정규화 심볼 e.g. "BTC/KRW"
    """
    return f"{target.upper()}/{quote.upper()}"


def _parse_currencies(market: str) -> tuple[str, str]:
    """CoinOne 마켓 코드 (target_currency 대문자) → (quote_currency, target_currency).

    CoinOne SymbolMapper 마켓 코드: target_currency 대문자 (예: "BTC")
    v1 범위에서 quote_currency는 항상 "KRW" 고정.

    Args:
        market: CoinOne 마켓 코드 (target_currency 대문자) e.g. "BTC"

    Returns:
        (quote_currency, target_currency) 튜플 e.g. ("KRW", "BTC")
    """
    return QUOTE_CURRENCY, market.upper()


def parse_ticker(data: dict[str, Any]) -> Ticker:
    """CoinOne REST /public/v2/ticker_new 또는 WS TICKER 응답 → Ticker 변환.

    REST 응답에서는 tickers[0]를 전달, WS 응답에서는 data 필드를 전달.

    CoinOne 필드 매핑:
      last              → price (현재가)
      first             → open_price (시가)
      high              → high_price (고가)
      low               → low_price (저가)
      target_volume     → volume (거래량, target currency)
      quote_volume      → trade_value (거래대금, KRW)
      (last - first) / first → change_rate (계산 필요)
      timestamp (ms)    → timestamp (UTC datetime)
      target_currency   → market

    change_rate 계산 방어 코드 (first=0 엣지케이스):
      change_rate = (last - first) / first if first != Decimal("0") else Decimal("0")

    Args:
        data: CoinOne ticker 응답 dict (tickers[0] 또는 WS data)

    Returns:
        Ticker 모델

    Raises:
        ExchangeDataError: 필드 누락 또는 타입 오류
    """
    try:
        target = data.get("target_currency", "")
        quote = data.get("quote_currency", QUOTE_CURRENCY)
        market = target.upper() if target else ""
        symbol = _to_symbol(quote, target)

        last = Decimal(str(data["last"]))
        first = Decimal(str(data["first"]))
        high = Decimal(str(data["high"]))
        low = Decimal(str(data["low"]))
        target_volume = Decimal(str(data.get("target_volume", "0")))
        quote_volume = Decimal(str(data.get("quote_volume", "0")))

        if first != Decimal("0"):
            change_rate = (last - first) / first
        else:
            change_rate = Decimal("0")

        ts_ms = int(data["timestamp"])
        timestamp = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.UTC)

        return Ticker(
            exchange=ExchangeType.COINONE,
            symbol=symbol,
            market=market,
            price=last,
            open_price=first,
            high_price=high,
            low_price=low,
            volume=target_volume,
            trade_value=quote_volume,
            change_rate=change_rate,
            timestamp=timestamp,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("coinone", f"Failed to parse ticker: {exc}") from exc


def parse_orderbook(data: dict[str, Any], depth: int = 10) -> OrderBook:
    """CoinOne REST /public/v2/orderbook 또는 WS ORDERBOOK 응답 → OrderBook 변환.

    CoinOne 필드 매핑:
      asks[].price, asks[].qty → asks (오름차순)
      bids[].price, bids[].qty → bids (내림차순)
      target_currency           → market
      timestamp                 → timestamp (ms)

    Args:
        data: CoinOne orderbook 응답 dict
        depth: 반환할 최대 호가 개수

    Returns:
        OrderBook 모델

    Raises:
        ExchangeDataError: 필드 누락 또는 타입 오류
    """
    try:
        target = data.get("target_currency", "")
        quote = data.get("quote_currency", QUOTE_CURRENCY)
        market = target.upper() if target else ""
        symbol = _to_symbol(quote, target)

        ts_ms = int(data["timestamp"])
        timestamp = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.UTC)

        raw_asks = data.get("asks", [])[:depth]
        raw_bids = data.get("bids", [])[:depth]

        asks = sorted(
            [
                OrderBookEntry(
                    price=Decimal(str(u["price"])),
                    quantity=Decimal(str(u["qty"])),
                )
                for u in raw_asks
            ],
            key=lambda e: e.price,
        )
        bids = sorted(
            [
                OrderBookEntry(
                    price=Decimal(str(u["price"])),
                    quantity=Decimal(str(u["qty"])),
                )
                for u in raw_bids
            ],
            key=lambda e: e.price,
            reverse=True,
        )

        return OrderBook(
            exchange=ExchangeType.COINONE,
            symbol=symbol,
            market=market,
            asks=asks,
            bids=bids,
            timestamp=timestamp,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("coinone", f"Failed to parse orderbook: {exc}") from exc


def parse_candle(data: dict[str, Any], target_currency: str, timeframe: str) -> Candle:
    """CoinOne REST /public/v2/chart 단일 캔들 dict → Candle 변환.

    CoinOne 필드 매핑:
      open               → open
      high               → high
      low                → low
      close              → close
      target_volume      → volume
      timestamp (ms)     → timestamp (UTC datetime)

    Args:
        data: CoinOne chart 응답의 단일 캔들 dict
        target_currency: 마켓 코드 (대문자) e.g. "BTC"
        timeframe: 타임프레임 문자열 e.g. "1h"

    Returns:
        Candle 모델

    Raises:
        ExchangeDataError: 필드 누락 또는 타입 오류
    """
    try:
        market = target_currency.upper()
        symbol = _to_symbol(QUOTE_CURRENCY, target_currency)

        ts_ms = int(data["timestamp"])
        timestamp = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.UTC)

        return Candle(
            exchange=ExchangeType.COINONE,
            symbol=symbol,
            market=market,
            timeframe=timeframe,
            open=Decimal(str(data["open"])),
            high=Decimal(str(data["high"])),
            low=Decimal(str(data["low"])),
            close=Decimal(str(data["close"])),
            volume=Decimal(str(data.get("target_volume", "0"))),
            timestamp=timestamp,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("coinone", f"Failed to parse candle: {exc}") from exc


def parse_order_result(data: dict[str, Any]) -> OrderResult:
    """CoinOne REST /v2.1/order POST 응답 → OrderResult 변환.

    CoinOne place_order 응답 필드:
      order_id           → exchange_order_id
      side (BUY/SELL)    → side
      type (LIMIT/MARKET)→ method
      qty                → quantity
      price              → price

    Note:
        CoinOne place_order 응답은 order_id만 반환하는 경우도 있음.
        최소 필드: order_id.

    Args:
        data: CoinOne order 응답 dict

    Returns:
        OrderResult 모델

    Raises:
        ExchangeDataError: 필드 누락 또는 타입 오류
    """
    try:
        order_id = data["order_id"]

        side_raw = data.get("side", "BUY").upper()
        side = OrderSide.BUY if side_raw == "BUY" else OrderSide.SELL

        type_raw = data.get("type", "LIMIT").upper()
        method = OrderMethod.LIMIT if type_raw == "LIMIT" else OrderMethod.MARKET

        qty_raw = data.get("qty") or data.get("amount", "0")
        quantity = Decimal(str(qty_raw)) if qty_raw else Decimal("0")

        price_raw = data.get("price")
        price = Decimal(str(price_raw)) if price_raw else None

        # place_order 응답은 PENDING 상태로 시작
        status = OrderStatus.PENDING

        target = data.get("target_currency", "")
        quote = data.get("quote_currency", QUOTE_CURRENCY)
        market = target.upper() if target else ""

        created_at = dt.datetime.now(tz=dt.UTC)

        return OrderResult(
            exchange_order_id=order_id,
            market=market,
            side=side,
            method=method,
            status=status,
            quantity=quantity,
            executed_quantity=Decimal("0"),
            price=price,
            fee=Decimal("0"),
            fee_currency=quote,
            created_at=created_at,
        )
    except ExchangeDataError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("coinone", f"Failed to parse order result: {exc}") from exc


def parse_cancel_result(data: dict[str, Any]) -> OrderResult:
    """CoinOne REST /v2.1/order/cancel 응답 전용 파서.

    주문 상태 추론:
    - remain_qty == "0" and traded_qty > "0" → FILLED (이미 체결 완료)
    - remain_qty > "0" and traded_qty > "0" → PARTIAL (부분 체결 후 취소)
    - remain_qty > "0" and traded_qty == "0" → CANCELLED (미체결 취소)

    CoinOne 필드 매핑:
      order_id           → exchange_order_id
      side               → side
      qty, remain_qty, traded_qty → quantity/executed_quantity/status
      fee                → fee
      avg_price          → avg_executed_price
      canceled_at (ms)   → created_at

    Args:
        data: CoinOne cancel order 응답 dict

    Returns:
        OrderResult 모델

    Raises:
        ExchangeDataError: 필드 누락 또는 타입 오류
    """
    try:
        order_id = data["order_id"]

        side_raw = data.get("side", "BUY").upper()
        side = OrderSide.BUY if side_raw == "BUY" else OrderSide.SELL

        qty = Decimal(str(data.get("qty", "0")))
        remain_qty = Decimal(str(data.get("remain_qty", "0")))
        traded_qty = Decimal(str(data.get("traded_qty", "0")))

        # 주문 상태 추론
        if remain_qty == Decimal("0") and traded_qty > Decimal("0"):
            status = OrderStatus.FILLED
        elif remain_qty > Decimal("0") and traded_qty > Decimal("0"):
            status = OrderStatus.PARTIAL
        else:
            status = OrderStatus.CANCELLED

        price_raw = data.get("price")
        price = Decimal(str(price_raw)) if price_raw else None

        avg_raw = data.get("avg_price")
        avg_price = Decimal(str(avg_raw)) if avg_raw and avg_raw != "0" else None

        fee_raw = data.get("fee", "0")
        fee = Decimal(str(fee_raw)) if fee_raw else Decimal("0")

        target = data.get("target_currency", "")
        quote = data.get("quote_currency", QUOTE_CURRENCY)
        market = target.upper() if target else ""

        canceled_at_ms = data.get("canceled_at", 0)
        created_at = dt.datetime.fromtimestamp(int(canceled_at_ms) / 1000, tz=dt.UTC)

        return OrderResult(
            exchange_order_id=order_id,
            market=market,
            side=side,
            method=OrderMethod.LIMIT,  # cancel 응답에서 type 필드 없을 수 있음
            status=status,
            quantity=qty,
            executed_quantity=traded_qty,
            price=price,
            avg_executed_price=avg_price,
            fee=fee,
            fee_currency=quote,
            created_at=created_at,
        )
    except ExchangeDataError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("coinone", f"Failed to parse cancel result: {exc}") from exc


def parse_balance(data: dict[str, Any]) -> Balance:
    """CoinOne REST /v2.1/account/balance/all 단일 잔고 dict → Balance 변환.

    CoinOne 필드 매핑:
      currency          → currency (대문자 변환)
      available         → available
      limit             → locked (CoinOne은 "limit" 명칭 사용)

    Args:
        data: CoinOne 잔고 응답의 단일 balance dict

    Returns:
        Balance 모델

    Raises:
        ExchangeDataError: 필드 누락 또는 타입 오류
    """
    try:
        return Balance(
            currency=data["currency"].upper(),
            available=Decimal(str(data["available"])),
            locked=Decimal(str(data.get("limit", "0"))),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("coinone", f"Failed to parse balance: {exc}") from exc


def parse_trading_fee(data: dict[str, Any], market: str) -> TradingFee:
    """CoinOne REST /v2.1/account/trade_fee 응답 → TradingFee 변환.

    CoinOne 필드 매핑:
      maker_fee         → maker_fee
      taker_fee         → taker_fee

    Args:
        data: CoinOne trade_fee 응답 dict
        market: CoinOne 마켓 코드 (target_currency 대문자) e.g. "BTC"

    Returns:
        TradingFee 모델

    Raises:
        ExchangeDataError: 필드 누락 또는 타입 오류
    """
    try:
        return TradingFee(
            exchange=ExchangeType.COINONE,
            market=market,
            maker_fee=Decimal(str(data["maker_fee"])),
            taker_fee=Decimal(str(data["taker_fee"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeDataError("coinone", f"Failed to parse trading fee: {exc}") from exc
