"""CoinOne Provider 상수 및 매핑 테이블."""
from __future__ import annotations

from decimal import Decimal

from ..enums import OrderStatus
from ..exceptions import (
    ExchangeAuthError,
    ExchangeError,
    ExchangeInsufficientBalanceError,
    ExchangeInvalidSymbolError,
    ExchangeOrderError,
    ExchangePermissionError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)

# ── REST / WebSocket URL ──────────────────────────────────────────────────────

COINONE_REST_BASE_URL: str = "https://api.coinone.co.kr"
COINONE_WS_URL: str = "wss://stream.coinone.co.kr"

# ── 타임프레임 → CoinOne chart interval 매핑 ──────────────────────────────────
# CoinOne은 interval 파라미터를 직접 사용
TIMEFRAME_TO_INTERVAL: dict[str, str] = {
    "1m":  "1m",
    "3m":  "3m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1d",
    "1w":  "1w",
    "1M":  "1mon",
}

# ── CoinOne 에러 코드(숫자 문자열) → ExchangeError 서브클래스 매핑 ───────────────
# CoinOne 에러 응답 형식: {"result": "error", "error_code": "4", "error_msg": "..."}
COINONE_ERROR_MAP: dict[str, type[ExchangeError]] = {
    # 인증/권한 에러
    "4":   ExchangeRateLimitError,          # Blocked user access
    "11":  ExchangeAuthError,               # Access token is missing
    "12":  ExchangeAuthError,               # Invalid access token
    "23":  ExchangeAuthError,               # Invalid App Secret
    "40":  ExchangePermissionError,         # Invalid API permission
    "50":  ExchangeAuthError,               # KYC authentication required
    "53":  ExchangeAuthError,               # Two Factor Auth Fail
    # Payload/Signature 에러
    "120": ExchangeAuthError,               # V2 API payload is missing
    "121": ExchangeAuthError,               # V2 API signature is missing
    "122": ExchangeAuthError,               # V2 API nonce is missing
    "123": ExchangeAuthError,               # V2 API signature is not correct
    "130": ExchangeAuthError,               # Nonce must be positive integer
    "131": ExchangeAuthError,               # Nonce must be bigger than last nonce
    "132": ExchangeAuthError,               # Nonce already used
    "133": ExchangeAuthError,               # Nonce must be UUID format
    # 주문/잔고 에러
    "101": ExchangeOrderError,              # Invalid format
    "103": ExchangeInsufficientBalanceError, # Lack of Balance
    "104": ExchangeOrderError,              # Order id does not exist
    "105": ExchangeOrderError,              # Price is not correct
    "107": ExchangeOrderError,              # Parameter error
    "108": ExchangeInvalidSymbolError,      # Unknown cryptocurrency
    "109": ExchangeInvalidSymbolError,      # Unknown cryptocurrency pair
    "111": ExchangeOrderError,              # Price difference too large
    "113": ExchangeOrderError,              # Quantity is too low
    "114": ExchangeOrderError,              # Invalid order amount
    "115": ExchangeOrderError,              # Maximum quantity exceeded
    "116": ExchangeOrderError,              # Already traded
    "117": ExchangeOrderError,              # Already canceled
    # 가격 제한 에러
    "300": ExchangeOrderError,              # Invalid order information
    "301": ExchangeOrderError,              # Sell below base price
    "302": ExchangeOrderError,              # Sell above base price
    "303": ExchangeOrderError,              # Buy below base price
    "304": ExchangeOrderError,              # Buy above base price
    "305": ExchangeOrderError,              # Invalid quantity
    "306": ExchangeOrderError,              # Below minimum amount
    "307": ExchangeOrderError,              # Exceeds maximum amount
    # 서버 에러
    "405": ExchangeUnavailableError,        # Server error
}

# HTTP 상태 코드 기반 폴백 매핑 (error_code 매칭 실패 시)
HTTP_STATUS_ERROR_MAP: dict[int, type[ExchangeError]] = {
    401: ExchangeAuthError,
    403: ExchangePermissionError,
    429: ExchangeRateLimitError,
}

# ── CoinOne → 공통 OrderStatus 매핑 ──────────────────────────────────────────
# cancel_order 응답에서 주문 상태 추론 (remain_qty, traded_qty 기반)
COINONE_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "live":      OrderStatus.PENDING,
    "partially_filled": OrderStatus.PARTIAL,
    "filled":    OrderStatus.FILLED,
    "canceled":  OrderStatus.CANCELLED,
}

# ── 수수료 기본값 ─────────────────────────────────────────────────────────────
COINONE_DEFAULT_MAKER_FEE: Decimal = Decimal("0.0002")  # 0.02%
COINONE_DEFAULT_TAKER_FEE: Decimal = Decimal("0.0002")  # 0.02%

# ── 정적 마켓 목록 (initialize() 동적 로드 실패 시 fallback) ─────────────────────
# CoinOne SymbolMapper 값: target_currency 대문자 (API 응답 기준)
COINONE_STATIC_MARKETS: dict[str, str] = {
    "BTC/KRW":   "BTC",
    "ETH/KRW":   "ETH",
    "XRP/KRW":   "XRP",
    "SOL/KRW":   "SOL",
    "ADA/KRW":   "ADA",
    "DOGE/KRW":  "DOGE",
    "DOT/KRW":   "DOT",
    "AVAX/KRW":  "AVAX",
    "MATIC/KRW": "MATIC",
    "LINK/KRW":  "LINK",
    "ATOM/KRW":  "ATOM",
    "NEAR/KRW":  "NEAR",
    "TRX/KRW":   "TRX",
    "LTC/KRW":   "LTC",
    "BCH/KRW":   "BCH",
}

# ── 호가 size 매핑 ────────────────────────────────────────────────────────────
# CoinOne orderbook API는 size 파라미터가 5/10/15/16 중 하나만 허용
_ORDERBOOK_VALID_SIZES: tuple[int, ...] = (5, 10, 15, 16)


def get_orderbook_size(depth: int) -> int:
    """depth를 CoinOne 허용 size 중 가장 가까운 값으로 매핑.

    Args:
        depth: 요청 호가 개수

    Returns:
        CoinOne API 허용 size (5/10/15/16)
    """
    for s in _ORDERBOOK_VALID_SIZES:
        if depth <= s:
            return s
    return 16
