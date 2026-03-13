"""거래소 Provider 공통 기반 구현체 — Rate Limiter + Circuit Breaker 주입."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from app.core.rate_limiter import ExchangeRateLimiter, RateLimitResult

from .base import ExchangeProvider
from .circuit_breaker import CircuitBreaker
from .enums import ExchangeType
from .exceptions import ExchangeRateLimitError

logger = logging.getLogger(__name__)
T = TypeVar("T")


class BaseExchangeProvider(ExchangeProvider):
    """공통 HTTP/WS 클라이언트 + Rate Limiter + Circuit Breaker 통합 기반 클래스.

    구체 거래소 구현체는 이 클래스를 상속하고 추상 메서드를 구현한다.
    모든 REST 호출은 `_execute_rest()` 래퍼를 통해야 한다.
    """

    def __init__(
        self,
        exchange_type: ExchangeType,
        api_key: str,
        api_secret: str,
        rate_limiter: ExchangeRateLimiter,
        circuit_breaker: CircuitBreaker,
        user_id: str,
    ) -> None:
        self._exchange_type = exchange_type
        self._api_key = api_key
        self._api_secret = api_secret
        self._rate_limiter = rate_limiter
        self._circuit_breaker = circuit_breaker
        self._user_id = user_id
        self._http_client: httpx.AsyncClient | None = None
        self._ws_connected: bool = False

    @property
    def exchange_type(self) -> ExchangeType:
        return self._exchange_type

    @property
    def is_connected(self) -> bool:
        return self._ws_connected

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy init httpx 클라이언트 (HTTP/1.1 Keep-Alive 재사용)."""
        if self._http_client is None or self._http_client.is_closed:
            from app.core.config import settings

            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=float(settings.EXCHANGE_HTTP_TIMEOUT),
                    write=5.0,
                    pool=5.0,
                ),
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                ),
            )
        return self._http_client

    async def _execute_rest(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Rate Limiter → Circuit Breaker 순서로 REST 호출 래핑.

        1. Rate Limit 확인 (초과 시 ExchangeRateLimitError)
        2. Circuit Breaker를 통한 func 호출
        """
        rate_result: RateLimitResult = await self._rate_limiter.acquire(
            self._exchange_type.value, self._user_id
        )
        if not rate_result.allowed:
            raise ExchangeRateLimitError(
                self._exchange_type.value,
                retry_after_seconds=rate_result.retry_after_ms // 1000,
            )
        return await self._circuit_breaker.call(func, *args, **kwargs)

    async def initialize(self) -> None:
        """기본 초기화 — HTTP 클라이언트 준비."""
        await self._get_http_client()

    async def close(self) -> None:
        """기본 정리 — HTTP 클라이언트 종료 + WS 연결 해제."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        if self._ws_connected:
            await self.disconnect()
