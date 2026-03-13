"""거래소 Provider Factory + Registry."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from redis.asyncio import Redis

from app.core.rate_limiter import ExchangeRateLimiter

from .base import ExchangeProvider
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .enums import ExchangeType
from .exceptions import (
    ExchangeAuthError,
    ExchangeInsufficientBalanceError,
    ExchangeInvalidSymbolError,
    ExchangePermissionError,
)

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.models.exchange import UserExchangeAccount

logger = logging.getLogger(__name__)
P = TypeVar("P", bound=ExchangeProvider)

# ── Circuit Breaker 제외 예외 (사용자 오류 — 장애 카운트 제외) ───────────────────

_EXCLUDED_FROM_CB = (
    ExchangeAuthError,
    ExchangePermissionError,
    ExchangeInvalidSymbolError,
    ExchangeInsufficientBalanceError,
)


# ── Registry ──────────────────────────────────────────────────────────────────


class ExchangeProviderRegistry:
    """등록된 Provider 클래스 관리 레지스트리 (클래스 변수 전역 관리)."""

    _registry: dict[ExchangeType, type[ExchangeProvider]] = {}

    @classmethod
    def register(cls, exchange_type: ExchangeType) -> Callable[[type[P]], type[P]]:
        """클래스 데코레이터 방식 Provider 등록.

        Example:
            @ExchangeProviderRegistry.register(ExchangeType.UPBIT)
            class UpbitProvider(BaseExchangeProvider):
                ...
        """

        def decorator(provider_cls: type[P]) -> type[P]:
            cls._registry[exchange_type] = provider_cls
            logger.debug(
                "Registered provider: %s → %s", exchange_type, provider_cls.__name__
            )
            return provider_cls

        return decorator

    @classmethod
    def get(cls, exchange_type: ExchangeType) -> type[ExchangeProvider]:
        """Raises:
        KeyError: 등록되지 않은 거래소
        """
        if exchange_type not in cls._registry:
            raise KeyError(f"No provider registered for exchange: {exchange_type}")
        return cls._registry[exchange_type]

    @classmethod
    def registered_exchanges(cls) -> list[ExchangeType]:
        return list(cls._registry.keys())


# ── Factory ───────────────────────────────────────────────────────────────────


class ExchangeProviderFactory:
    """싱글턴 Factory — Circuit Breaker + Rate Limiter 주입 Provider 생성.

    Circuit Breaker는 거래소별로 공유 (장애 상태 서버 전체에서 유지).
    """

    _instance: ExchangeProviderFactory | None = None

    def __init__(self, redis: Redis, settings: "Settings") -> None:
        self._rate_limiter = ExchangeRateLimiter(redis)
        default_cfg = CircuitBreakerConfig(
            failure_threshold=settings.CB_FAILURE_THRESHOLD,
            failure_rate_threshold=settings.CB_FAILURE_RATE_THRESHOLD,
            failure_rate_window=settings.CB_FAILURE_RATE_WINDOW,
            recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
            half_open_max_calls=1,
            excluded_exceptions=_EXCLUDED_FROM_CB,
        )
        self._circuit_breakers: dict[ExchangeType, CircuitBreaker] = {
            exchange_type: CircuitBreaker(name=exchange_type.value, config=default_cfg)
            for exchange_type in ExchangeType
        }
        self._active_providers: list[ExchangeProvider] = []

    @classmethod
    def instance(cls) -> ExchangeProviderFactory:
        """싱글턴 인스턴스 반환."""
        if cls._instance is None:
            raise RuntimeError("ExchangeProviderFactory not initialized.")
        return cls._instance

    @classmethod
    def init(cls, redis: Redis) -> ExchangeProviderFactory:
        """싱글턴 초기화 — lifespan startup에서 1회 호출."""
        from app.core.config import settings

        cls._instance = cls(redis, settings)
        return cls._instance

    def register_defaults(self) -> None:
        """Mock Provider로 모든 거래소 기본 등록.

        실제 거래소 구현체는 M3+(Upbit) 마일스톤에서 교체 등록.
        """
        from .mock_provider import MockExchangeProvider

        for exchange_type in ExchangeType:
            if exchange_type not in ExchangeProviderRegistry._registry:
                ExchangeProviderRegistry._registry[exchange_type] = MockExchangeProvider

    def create(
        self,
        exchange_type: ExchangeType,
        api_key: str,
        api_secret: str,
        user_id: str,
    ) -> ExchangeProvider:
        """평문 API 키로 Provider 인스턴스 생성.

        Raises:
            KeyError: 등록되지 않은 거래소
        """
        provider_cls = ExchangeProviderRegistry.get(exchange_type)
        cb = self._circuit_breakers[exchange_type]
        provider = provider_cls(
            exchange_type=exchange_type,
            api_key=api_key,
            api_secret=api_secret,
            rate_limiter=self._rate_limiter,
            circuit_breaker=cb,
            user_id=user_id,
        )
        self._active_providers.append(provider)
        return provider

    async def create_from_account(
        self,
        account: "UserExchangeAccount",
        encryption_key: bytes,
    ) -> ExchangeProvider:
        """DB의 UserExchangeAccount에서 복호화 후 Provider 생성.

        Raises:
            KeyError: 등록되지 않은 거래소
            ValueError: 복호화 실패
        """
        from app.core.encryption import decrypt_value

        api_key = decrypt_value(account.api_key_encrypted, encryption_key)
        api_secret = decrypt_value(account.api_secret_encrypted, encryption_key)
        return self.create(
            exchange_type=ExchangeType(account.exchange_type),
            api_key=api_key,
            api_secret=api_secret,
            user_id=str(account.user_id),
        )

    def get_circuit_breaker(self, exchange_type: ExchangeType) -> CircuitBreaker:
        """거래소별 Circuit Breaker 조회 (헬스체크/모니터링용)."""
        return self._circuit_breakers[exchange_type]

    async def close_all(self) -> None:
        """모든 활성 Provider 정리 — lifespan shutdown에서 호출."""
        for provider in self._active_providers:
            try:
                await provider.close()
            except Exception:
                logger.exception("Error closing provider: %s", provider.exchange_type)
        self._active_providers.clear()
        ExchangeProviderFactory._instance = None
