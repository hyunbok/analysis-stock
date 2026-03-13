"""providers 패키지 Public API.

외부 (services/, ws/, tasks/, trading/) 에서는 이 __init__.py를 통해서만 import.
providers 내부 모듈 직접 import 금지.
"""
from .base import ExchangeProvider, ExchangeRestProvider, ExchangeStreamProvider
from .base_impl import BaseExchangeProvider
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .enums import (
    ApiKeyPermission,
    CircuitState,
    ExchangeType,
    OrderMethod,
    OrderSide,
    OrderStatus,
)
from .exceptions import (
    ExchangeAuthError,
    ExchangeDataError,
    ExchangeError,
    ExchangeInsufficientBalanceError,
    ExchangeInvalidSymbolError,
    ExchangeNetworkError,
    ExchangeOrderError,
    ExchangePermissionError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from .factory import ExchangeProviderFactory, ExchangeProviderRegistry
from .upbit import UpbitProvider  # noqa: F401 — import 시 자동 Registry 등록
from .types import (
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

__all__ = [
    # Base classes
    "ExchangeProvider",
    "ExchangeRestProvider",
    "ExchangeStreamProvider",
    "BaseExchangeProvider",
    # Providers
    "UpbitProvider",
    # Factory
    "ExchangeProviderFactory",
    "ExchangeProviderRegistry",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    # Enums
    "ExchangeType",
    "OrderSide",
    "OrderMethod",
    "OrderStatus",
    "ApiKeyPermission",
    # Types
    "Ticker",
    "OrderBook",
    "OrderBookEntry",
    "Candle",
    "Order",
    "OrderResult",
    "Balance",
    "TradingFee",
    "ApiKeyInfo",
    "SymbolMapper",
    # Exceptions
    "ExchangeError",
    "ExchangeAuthError",
    "ExchangePermissionError",
    "ExchangeRateLimitError",
    "ExchangeOrderError",
    "ExchangeInsufficientBalanceError",
    "ExchangeNetworkError",
    "ExchangeUnavailableError",
    "ExchangeInvalidSymbolError",
    "ExchangeDataError",
]
