"""Upbit Provider 상수 및 매핑 테이블."""
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
)

# ── REST / WebSocket URL ──────────────────────────────────────────────────────

UPBIT_REST_BASE_URL: str = "https://api.upbit.com/v1"
UPBIT_WS_URL: str = "wss://api.upbit.com/websocket/v1"

# ── 타임프레임 → Upbit candle 엔드포인트 경로 매핑 ────────────────────────────────
# Upbit: /candles/minutes/{unit}, /candles/days, /candles/weeks, /candles/months
# "1h" → "minutes/60" (Upbit은 hours 엔드포인트 미제공)
TIMEFRAME_TO_CANDLE_PATH: dict[str, str] = {
    "1m":  "minutes/1",
    "3m":  "minutes/3",
    "5m":  "minutes/5",
    "15m": "minutes/15",
    "30m": "minutes/30",
    "1h":  "minutes/60",
    "4h":  "minutes/240",
    "1d":  "days",
    "1w":  "weeks",
    "1M":  "months",
}

# ── Upbit 에러 코드 → ExchangeError 서브클래스 매핑 ──────────────────────────────
# Upbit 에러 응답 형식: { "error": { "name": "...", "message": "..." } }
UPBIT_ERROR_MAP: dict[str, type[ExchangeError]] = {
    "invalid_access_key":        ExchangeAuthError,
    "expired_access_key":        ExchangeAuthError,
    "nonce_used":                ExchangeAuthError,       # nonce 재사용 공격 방지
    "jwt_verification":          ExchangeAuthError,
    "no_authorization_token":    ExchangeAuthError,
    "no_authorization_ip":       ExchangePermissionError,  # IP whitelist 제한
    "out_of_scope":              ExchangePermissionError,
    "exceed_order_limit":        ExchangeRateLimitError,
    "exceed_api_limit":          ExchangeRateLimitError,
    "insufficient_funds_ask":    ExchangeInsufficientBalanceError,  # 매도 잔고 부족
    "insufficient_funds_bid":    ExchangeInsufficientBalanceError,  # 매수 잔고 부족
    "under_min_total_ask":       ExchangeOrderError,      # 최소 주문금액 미달 (매도)
    "under_min_total_bid":       ExchangeOrderError,      # 최소 주문금액 미달 (매수)
    "unknown_market":            ExchangeInvalidSymbolError,
    "validation_error":          ExchangeOrderError,
    "create_ask_error":          ExchangeOrderError,
    "create_bid_error":          ExchangeOrderError,
}

# HTTP 상태 코드 기반 폴백 매핑 (error.name 매칭 실패 시)
HTTP_STATUS_ERROR_MAP: dict[int, type[ExchangeError]] = {
    401: ExchangeAuthError,
    403: ExchangePermissionError,
    404: ExchangeInvalidSymbolError,
    418: ExchangeRateLimitError,    # Upbit 고유: 과도한 요청 시 IP 차단
    429: ExchangeRateLimitError,
}

# ── Upbit → 공통 OrderStatus 매핑 ────────────────────────────────────────────
# Upbit 주문 상태: wait | watch | done | cancel
UPBIT_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "wait":   OrderStatus.PENDING,
    "watch":  OrderStatus.PENDING,
    "done":   OrderStatus.FILLED,
    "cancel": OrderStatus.CANCELLED,
}

# ── 수수료 기본값 ─────────────────────────────────────────────────────────────
# verify_api_key 시점에 로드, get_trading_fee에서 캐싱
UPBIT_DEFAULT_FEE_RATE: Decimal = Decimal("0.0005")  # 0.05%

# ── 정적 마켓 목록 (initialize() 동적 로드 실패 시 fallback) ─────────────────────
# GET /v1/market/all 성공 시 SymbolMapper._MAPS[UPBIT]를 동적으로 갱신
UPBIT_STATIC_MARKETS: dict[str, str] = {
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
}
