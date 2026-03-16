"""Circuit Breaker 구현 — 거래소 장애 감지 및 차단."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from .enums import CircuitState
from .exceptions import ExchangeUnavailableError

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class CircuitBreakerConfig:
    """Circuit Breaker 설정값 (설계서 §4.2 기준)."""

    failure_threshold: int = 5
    """연속 실패 허용 횟수 (CLOSED → OPEN 전환)."""

    failure_rate_threshold: float = 0.5
    """실패율 임계값 (50%). window 내 실패율이 이를 초과하면 OPEN."""

    failure_rate_window: int = 30
    """실패율 측정 윈도우 (초). 최소 5개 샘플 이상 시 실패율 체크."""

    recovery_timeout: int = 60
    """OPEN 상태 유지 시간 (초). 경과 후 HALF_OPEN으로 자동 전환."""

    half_open_max_calls: int = 1
    """HALF_OPEN에서 허용할 최대 시험 호출 수."""

    excluded_exceptions: tuple[type[Exception], ...] = field(default_factory=tuple)
    """서킷 카운트에서 제외할 예외 (사용자 오류: Auth, Permission, InvalidSymbol 등)."""


class CircuitBreaker:
    """단일 거래소에 대한 Circuit Breaker.

    asyncio.Lock으로 상태 전환 보호 (asyncio 단일 이벤트 루프 전제).
    슬라이딩 윈도우 방식: 연속 실패 OR 실패율 초과 시 OPEN 전환.

    상태 전이:
        CLOSED → OPEN: failure_threshold 연속 실패 OR failure_rate_window 내 failure_rate_threshold 초과
        OPEN → HALF_OPEN: recovery_timeout 경과
        HALF_OPEN → CLOSED: 시험 호출 성공
        HALF_OPEN → OPEN: 시험 호출 실패
    """

    def __init__(self, name: str, config: CircuitBreakerConfig) -> None:
        self._name = name
        self._config = config
        self._state = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._half_open_calls: int = 0
        self._opened_at: float | None = None
        # 슬라이딩 윈도우: (monotonic_timestamp, success: bool)
        self._window: deque[tuple[float, bool]] = deque()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._consecutive_failures

    @property
    def name(self) -> str:
        return self._name

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: object,
        **kwargs: object,
    ) -> T:
        """Circuit Breaker를 통한 async 함수 호출.

        Raises:
            ExchangeUnavailableError: OPEN 상태 (차단 중) 또는 HALF_OPEN 최대 시험 호출 초과
        """
        async with self._lock:
            # OPEN → HALF_OPEN 전환 체크
            if (
                self._state == CircuitState.OPEN
                and self._opened_at is not None
                and time.monotonic() - self._opened_at >= self._config.recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("CircuitBreaker[%s] OPEN → HALF_OPEN", self._name)

            if self._state == CircuitState.OPEN:
                raise ExchangeUnavailableError(
                    self._name,
                    f"Circuit breaker is OPEN for {self._name}.",
                )

            if (
                self._state == CircuitState.HALF_OPEN
                and self._half_open_calls >= self._config.half_open_max_calls
            ):
                raise ExchangeUnavailableError(
                    self._name,
                    f"Circuit breaker HALF_OPEN: max probe calls reached for {self._name}.",
                )

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            await self._record(success=True)
            return result
        except Exception as exc:
            if not isinstance(exc, self._config.excluded_exceptions):
                await self._record(success=False)
            raise

    async def _record(self, *, success: bool) -> None:
        """성공/실패 기록 및 상태 전이 처리."""
        now = time.monotonic()
        async with self._lock:
            self._window.append((now, success))
            # 윈도우 밖 오래된 항목 제거
            cutoff = now - self._config.failure_rate_window
            while self._window and self._window[0][0] < cutoff:
                self._window.popleft()

            if success:
                self._consecutive_failures = 0
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.CLOSED
                    logger.info(
                        "CircuitBreaker[%s] HALF_OPEN → CLOSED (recovered)", self._name
                    )
            else:
                self._consecutive_failures += 1
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.OPEN
                    self._opened_at = now
                    logger.warning("CircuitBreaker[%s] HALF_OPEN → OPEN", self._name)
                elif self._state == CircuitState.CLOSED and self._should_open():
                    self._state = CircuitState.OPEN
                    self._opened_at = now
                    logger.warning(
                        "CircuitBreaker[%s] CLOSED → OPEN (failures=%d)",
                        self._name,
                        self._consecutive_failures,
                    )
                    # TODO(v1-22): 시스템 알림 — PushService 주입 후 아래 코드 활성화
                    # 거래소 Circuit Breaker OPEN 시 해당 거래소를 사용 중인 사용자에게 알림
                    # push_service.send_system_alert()은 user_id가 필요하므로
                    # ExchangeAccountRepository를 통해 활성 사용자 목록 조회 후 발송 권장
                    # 예시:
                    # await push_service.send_system_alert(
                    #     user_id=user_id,
                    #     message=f"{self._name} 거래소 연결이 불안정합니다.",
                    #     severity="warning",
                    # )

    def _should_open(self) -> bool:
        """연속 실패 OR 실패율 초과 시 True."""
        if self._consecutive_failures >= self._config.failure_threshold:
            return True
        if len(self._window) >= 5:  # 최소 5개 샘플
            failed = sum(1 for _, ok in self._window if not ok)
            if failed / len(self._window) >= self._config.failure_rate_threshold:
                return True
        return False

    def reset(self) -> None:
        """강제 초기화 (테스트 및 수동 복구용)."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_calls = 0
        self._opened_at = None
        self._window.clear()
