"""거래소 추상화 계층 공통 Pydantic 데이터 모델."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from .enums import ApiKeyPermission, ExchangeType, OrderMethod, OrderSide, OrderStatus


# ── 시세 / 호가 ─────────────────────────────────────────────────────────────


class Ticker(BaseModel):
    """실시간 시세 스냅샷."""

    exchange: ExchangeType
    symbol: str           # 정규화 심볼 e.g. "BTC/KRW"
    market: str           # 거래소 내부 마켓 코드 e.g. "KRW-BTC"
    price: Decimal        # 현재가
    open_price: Decimal   # 24h 시가
    high_price: Decimal   # 24h 고가
    low_price: Decimal    # 24h 저가
    volume: Decimal       # 24h 거래량 (코인)
    trade_value: Decimal  # 24h 거래대금 (KRW/USD)
    change_rate: Decimal  # 24h 변동률 (소수: 0.05 = +5%)
    timestamp: datetime   # 거래소 기준 타임스탬프 (UTC)


class OrderBookEntry(BaseModel):
    """단일 호가."""

    price: Decimal
    quantity: Decimal


class OrderBook(BaseModel):
    """호가창 스냅샷."""

    exchange: ExchangeType
    symbol: str
    market: str
    asks: list[OrderBookEntry]  # 매도 호가, 오름차순 (낮은 가격 먼저)
    bids: list[OrderBookEntry]  # 매수 호가, 내림차순 (높은 가격 먼저)
    timestamp: datetime


class Candle(BaseModel):
    """OHLCV 캔들 데이터."""

    exchange: ExchangeType
    symbol: str
    market: str
    timeframe: str    # "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    timestamp: datetime  # 캔들 시작 시각 (UTC)


# ── 주문 ─────────────────────────────────────────────────────────────────────


class Order(BaseModel):
    """주문 요청 모델 (Provider.place_order() 입력)."""

    market: str               # 거래소 내부 마켓 코드
    side: OrderSide
    method: OrderMethod
    quantity: Decimal         # 수량 (코인 기준)
    price: Decimal | None = None  # 지정가 주문 시 필수, 시장가 시 None


class OrderResult(BaseModel):
    """주문 실행 결과 모델 (Provider.place_order() 반환)."""

    exchange_order_id: str
    market: str
    side: OrderSide
    method: OrderMethod
    status: OrderStatus
    quantity: Decimal
    executed_quantity: Decimal = Decimal("0")
    price: Decimal | None = None              # 주문 가격 (지정가)
    avg_executed_price: Decimal | None = None # 평균 체결 가격
    fee: Decimal = Decimal("0")
    fee_currency: str | None = None           # e.g. "KRW", "BNB"
    created_at: datetime
    executed_at: datetime | None = None


# ── 잔고 / 수수료 / API 키 ────────────────────────────────────────────────────


class Balance(BaseModel):
    """단일 자산 잔고."""

    currency: str       # e.g. "KRW", "BTC", "ETH"
    available: Decimal  # 사용 가능 (미잠금)
    locked: Decimal     # 잠금 (주문 중)

    @property
    def total(self) -> Decimal:
        return self.available + self.locked


class TradingFee(BaseModel):
    """수수료 정보."""

    exchange: ExchangeType
    market: str
    maker_fee: Decimal   # 지정가 수수료율 (소수: 0.001 = 0.1%)
    taker_fee: Decimal   # 시장가 수수료율


class ApiKeyInfo(BaseModel):
    """API 키 유효성 및 권한 정보 (verify_api_key() 반환)."""

    exchange: ExchangeType
    permissions: list[ApiKeyPermission]
    is_valid: bool
    error_message: str | None = None  # is_valid=False 시 사유
    has_withdraw_permission: bool = False  # 출금 권한 경고 표시용


# ── 심볼 변환 ──────────────────────────────────────────────────────────────────


class SymbolMapper:
    """거래소별 마켓 코드 ↔ 정규화 심볼 양방향 변환.

    정규화 심볼 형식: "{BASE}/{QUOTE}"  e.g. "BTC/KRW", "ETH/USDT"
    구체 구현체(UpbitProvider 등)에서 _MAPS 에 거래소 심볼을 추가한다.
    """

    _MAPS: dict[ExchangeType, dict[str, str]] = {
        ExchangeType.UPBIT: {
            "BTC/KRW":   "KRW-BTC",
            "ETH/KRW":   "KRW-ETH",
            "XRP/KRW":   "KRW-XRP",
            "SOL/KRW":   "KRW-SOL",
            "ADA/KRW":   "KRW-ADA",
            "DOGE/KRW":  "KRW-DOGE",
            "DOT/KRW":   "KRW-DOT",
            "AVAX/KRW":  "KRW-AVAX",
            "MATIC/KRW": "KRW-MATIC",
            "LINK/KRW":  "KRW-LINK",
            "ATOM/KRW":  "KRW-ATOM",
            "NEAR/KRW":  "KRW-NEAR",
            "TRX/KRW":   "KRW-TRX",
            "LTC/KRW":   "KRW-LTC",
            "BCH/KRW":   "KRW-BCH",
        },
        ExchangeType.COINONE: {
            "BTC/KRW": "btc",
            "ETH/KRW": "eth",
        },
        ExchangeType.COINBASE: {
            "BTC/USDT": "BTC-USDT",
            "ETH/USDT": "ETH-USDT",
        },
        ExchangeType.BINANCE: {
            "BTC/USDT": "BTCUSDT",
            "ETH/USDT": "ETHUSDT",
        },
    }
    # 역방향 캐시 (to_symbol 최초 호출 시 자동 생성)
    _REVERSE: dict[ExchangeType, dict[str, str]] = {}

    @classmethod
    def _build_reverse(cls) -> None:
        cls._REVERSE = {
            exchange: {v: k for k, v in maps.items()}
            for exchange, maps in cls._MAPS.items()
        }

    @classmethod
    def to_market(cls, exchange: ExchangeType, symbol: str) -> str:
        """정규화 심볼 → 거래소 마켓 코드.

        Raises:
            ExchangeInvalidSymbolError: 미지원 심볼
        """
        from .exceptions import ExchangeInvalidSymbolError

        mapping = cls._MAPS.get(exchange, {})
        if symbol not in mapping:
            raise ExchangeInvalidSymbolError(
                exchange.value, f"Unsupported symbol: {symbol}"
            )
        return mapping[symbol]

    @classmethod
    def to_symbol(cls, exchange: ExchangeType, market: str) -> str:
        """거래소 마켓 코드 → 정규화 심볼.

        Raises:
            ExchangeInvalidSymbolError: 미지원 마켓 코드
        """
        from .exceptions import ExchangeInvalidSymbolError

        if not cls._REVERSE:
            cls._build_reverse()
        reverse = cls._REVERSE.get(exchange, {})
        if market not in reverse:
            raise ExchangeInvalidSymbolError(
                exchange.value, f"Unsupported market: {market}"
            )
        return reverse[market]
