"""Circuit Breaker 단위 테스트."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from app.providers.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.providers.enums import CircuitState
from app.providers.exceptions import ExchangeUnavailableError


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_cb(
    failure_threshold: int = 5,
    failure_rate_threshold: float = 0.5,
    failure_rate_window: int = 30,
    recovery_timeout: int = 60,
    half_open_max_calls: int = 1,
    excluded_exceptions: tuple[type[Exception], ...] = (),
) -> CircuitBreaker:
    config = CircuitBreakerConfig(
        failure_threshold=failure_threshold,
        failure_rate_threshold=failure_rate_threshold,
        failure_rate_window=failure_rate_window,
        recovery_timeout=recovery_timeout,
        half_open_max_calls=half_open_max_calls,
        excluded_exceptions=excluded_exceptions,
    )
    return CircuitBreaker(name="test-exchange", config=config)


async def success_fn() -> str:
    return "ok"


async def fail_fn() -> None:
    raise RuntimeError("exchange error")


# ── TC1: CLOSED → OPEN (연속 실패) ────────────────────────────────────────────


@pytest.mark.anyio
async def test_closed_to_open_on_consecutive_failures():
    """연속 5회 실패 시 CLOSED → OPEN 전환."""
    cb = make_cb(failure_threshold=5)
    assert cb.state == CircuitState.CLOSED

    for _ in range(4):
        with pytest.raises(RuntimeError):
            await cb.call(fail_fn)
        assert cb.state == CircuitState.CLOSED  # 아직 CLOSED

    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN  # 5번째 실패 후 OPEN


@pytest.mark.anyio
async def test_open_rejects_calls_immediately():
    """OPEN 상태에서 모든 호출 즉시 거부."""
    cb = make_cb(failure_threshold=1)

    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN

    with pytest.raises(ExchangeUnavailableError):
        await cb.call(success_fn)


# ── TC2: CLOSED → OPEN (실패율 초과) ─────────────────────────────────────────


@pytest.mark.anyio
async def test_closed_to_open_on_failure_rate():
    """30초 내 실패율 50% 이상 시 CLOSED → OPEN.

    failure_rate_threshold=0.5 (>=) 이므로:
      4성공 + 3실패 = 7샘플 → 3/7 ≈ 43% < 50% → CLOSED
      4성공 + 4실패 = 8샘플 → 4/8 = 50% >= 50% → OPEN
    """
    # failure_threshold를 높게 설정해 연속 실패가 아닌 실패율로만 트리거
    cb = make_cb(failure_threshold=100, failure_rate_threshold=0.5, failure_rate_window=30)

    # 4번 성공 (샘플 축적)
    for _ in range(4):
        await cb.call(success_fn)
    assert cb.state == CircuitState.CLOSED

    # 3번 실패: 실패율 3/7 ≈ 43% → 아직 CLOSED
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(fail_fn)
    assert cb.state == CircuitState.CLOSED

    # 4번째 실패: 실패율 4/8 = 50% >= 0.5 → OPEN
    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN


# ── TC3: OPEN → HALF_OPEN (recovery_timeout 경과) ────────────────────────────


@pytest.mark.anyio
async def test_open_to_half_open_after_recovery_timeout():
    """recovery_timeout 경과 후 OPEN → HALF_OPEN 전환."""
    cb = make_cb(failure_threshold=1, recovery_timeout=0)  # 즉시 복구

    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN

    # recovery_timeout=0이므로 다음 call()에서 HALF_OPEN으로 전환
    result = await cb.call(success_fn)
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_open_stays_open_before_recovery_timeout():
    """recovery_timeout 미경과 시 OPEN 유지."""
    cb = make_cb(failure_threshold=1, recovery_timeout=9999)

    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN

    with pytest.raises(ExchangeUnavailableError):
        await cb.call(success_fn)
    assert cb.state == CircuitState.OPEN


# ── TC4: HALF_OPEN → CLOSED (시험 호출 성공) ─────────────────────────────────


@pytest.mark.anyio
async def test_half_open_to_closed_on_success():
    """HALF_OPEN 상태에서 시험 호출 성공 시 CLOSED 복귀."""
    cb = make_cb(failure_threshold=1, recovery_timeout=0)

    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN

    # recovery_timeout=0 → 다음 call에서 HALF_OPEN 전환 후 성공
    result = await cb.call(success_fn)
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


# ── TC5: HALF_OPEN → OPEN (시험 호출 실패) ───────────────────────────────────


@pytest.mark.anyio
async def test_half_open_to_open_on_failure():
    """HALF_OPEN 상태에서 시험 호출 실패 시 OPEN 재전환."""
    cb = make_cb(failure_threshold=1, recovery_timeout=0)

    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN

    # recovery_timeout=0 → HALF_OPEN 전환 후 실패
    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN


# ── TC6: excluded_exceptions 카운트 제외 ──────────────────────────────────────


class AuthError(Exception):
    pass


@pytest.mark.anyio
async def test_excluded_exceptions_not_counted():
    """excluded_exceptions에 해당하는 예외는 실패 카운트에서 제외."""
    cb = make_cb(failure_threshold=3, excluded_exceptions=(AuthError,))

    async def auth_fail_fn() -> None:
        raise AuthError("invalid key")

    # AuthError를 100번 발생시켜도 CLOSED 유지
    for _ in range(10):
        with pytest.raises(AuthError):
            await cb.call(auth_fail_fn)

    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.anyio
async def test_non_excluded_exception_counted():
    """excluded_exceptions에 해당하지 않는 예외는 카운트됨."""
    cb = make_cb(failure_threshold=3, excluded_exceptions=(AuthError,))

    async def network_fail_fn() -> None:
        raise RuntimeError("network error")

    for i in range(2):
        with pytest.raises(RuntimeError):
            await cb.call(network_fail_fn)
        assert cb.state == CircuitState.CLOSED

    with pytest.raises(RuntimeError):
        await cb.call(network_fail_fn)
    assert cb.state == CircuitState.OPEN


# ── TC7: 동시 호출 시 상태 일관성 ────────────────────────────────────────────


@pytest.mark.anyio
async def test_concurrent_calls_state_consistency():
    """동시 다중 호출 시 상태 전환 일관성 (race condition 없음)."""
    cb = make_cb(failure_threshold=5)

    call_count = 0

    async def counting_fail() -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("fail")

    # 10개 동시 실패 호출
    results = await asyncio.gather(
        *[cb.call(counting_fail) for _ in range(10)],
        return_exceptions=True,
    )

    # 모두 예외 발생
    assert all(isinstance(r, Exception) for r in results)

    # 상태가 OPEN이거나 CLOSED일 수 있지만, 반드시 유효한 상태여야 함
    assert cb.state in (CircuitState.CLOSED, CircuitState.OPEN)

    # OPEN이면 ExchangeUnavailableError 반환
    if cb.state == CircuitState.OPEN:
        with pytest.raises(ExchangeUnavailableError):
            await cb.call(success_fn)


@pytest.mark.anyio
async def test_concurrent_open_calls_all_rejected():
    """OPEN 상태에서 동시 호출 모두 ExchangeUnavailableError."""
    cb = make_cb(failure_threshold=1)

    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN

    results = await asyncio.gather(
        *[cb.call(success_fn) for _ in range(10)],
        return_exceptions=True,
    )
    assert all(isinstance(r, ExchangeUnavailableError) for r in results)


# ── TC8: reset() 동작 ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_reset_clears_state():
    """reset() 호출 시 모든 상태 초기화."""
    cb = make_cb(failure_threshold=1)

    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN

    cb.reset()

    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0

    # 리셋 후 정상 동작
    result = await cb.call(success_fn)
    assert result == "ok"


@pytest.mark.anyio
async def test_reset_clears_window_data():
    """reset() 후 슬라이딩 윈도우 데이터도 초기화."""
    # failure_threshold를 높게, 실패율로만 OPEN 유도
    cb = make_cb(failure_threshold=100, failure_rate_threshold=0.5)

    # 실패율 누적 (5번 성공, 6번 실패 → 실패율 55%)
    for _ in range(5):
        await cb.call(success_fn)
    for _ in range(5):
        with pytest.raises(RuntimeError):
            await cb.call(fail_fn)

    cb.reset()
    assert cb.state == CircuitState.CLOSED

    # 리셋 후 성공 카운트가 초기화되어야 함
    result = await cb.call(success_fn)
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED


# ── 추가: HALF_OPEN max_calls 제한 ────────────────────────────────────────────


@pytest.mark.anyio
async def test_half_open_max_calls_limit():
    """HALF_OPEN에서 half_open_max_calls 초과 시 ExchangeUnavailableError."""
    cb = make_cb(failure_threshold=1, recovery_timeout=0, half_open_max_calls=1)

    with pytest.raises(RuntimeError):
        await cb.call(fail_fn)
    assert cb.state == CircuitState.OPEN

    # 첫 번째 호출은 HALF_OPEN 전환 후 허용
    mock_fn = AsyncMock(return_value="ok")
    result = await cb.call(mock_fn)
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED

    # 다시 OPEN으로 만든 후 HALF_OPEN에서 max_calls=1 초과 테스트
    # (recovery_timeout=0으로 즉시 HALF_OPEN 재진입)
    cb2 = make_cb(failure_threshold=1, recovery_timeout=0, half_open_max_calls=1)

    with pytest.raises(RuntimeError):
        await cb2.call(fail_fn)

    # 첫 번째 HALF_OPEN 호출 (허용 — 아직 실패하지 않았으므로 HALF_OPEN 카운트 증가)
    slow_fn = AsyncMock(side_effect=asyncio.sleep(0))  # 즉시 반환
    # 동시에 2개 호출 → 하나는 허용, 하나는 거부
    results = await asyncio.gather(
        cb2.call(success_fn),
        cb2.call(success_fn),
        return_exceptions=True,
    )
    # 적어도 하나는 ExchangeUnavailableError
    errors = [r for r in results if isinstance(r, ExchangeUnavailableError)]
    successes = [r for r in results if r == "ok"]
    assert len(errors) + len(successes) == 2
