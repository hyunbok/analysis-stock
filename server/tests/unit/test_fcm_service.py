"""FCMService 단위 테스트.

설계서: docs/tasks/v1-22-fcm-push-notification-plan.md §5.1
테스트: Firebase 전송 mock (~12건)
"""
from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.services.fcm_service import FCMService

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────


def _make_settings(credentials: str = "") -> MagicMock:
    """테스트용 Settings (FIREBASE_CREDENTIALS_JSON 제어)."""
    s = MagicMock(spec=Settings)
    s.FIREBASE_CREDENTIALS_JSON = credentials
    return s


def _make_service(enabled: bool = False) -> FCMService:
    """FCMService 인스턴스 생성. enabled=True이면 _enabled 강제 설정."""
    svc = FCMService(_make_settings(credentials=""))
    if enabled:
        svc._enabled = True
    return svc


@pytest.fixture(autouse=True)
def patch_firebase_modules():
    """firebase_admin 모듈을 전체 mock으로 교체 (라이브러리 미설치 환경 지원)."""
    mock_fb = MagicMock()
    mock_fb._apps = {}
    mock_messaging = MagicMock()
    mock_credentials = MagicMock()
    with patch.dict(
        sys.modules,
        {
            "firebase_admin": mock_fb,
            "firebase_admin.messaging": mock_messaging,
            "firebase_admin.credentials": mock_credentials,
        },
    ):
        yield mock_messaging


# ── FCMService 초기화 ──────────────────────────────────────────────────────────


def test_fcm_disabled_when_credentials_empty() -> None:
    """FIREBASE_CREDENTIALS_JSON 미설정 → is_enabled=False."""
    svc = FCMService(_make_settings(credentials=""))
    assert svc.is_enabled is False


# ── send_notification ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_notification_disabled_returns_false() -> None:
    """FCM 비활성 → False 반환."""
    svc = _make_service(enabled=False)
    result = await svc.send_notification("token123", "제목", "본문")
    assert result is False


@pytest.mark.anyio
async def test_send_notification_enabled_success_returns_true() -> None:
    """FCM 활성 + 전송 성공 → True 반환."""
    svc = _make_service(enabled=True)
    with patch.object(asyncio, "to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = "msg_id_abc"
        result = await svc.send_notification(
            "token123", "제목", "본문", {"key": "val"}
        )
    assert result is True
    mock_thread.assert_called_once()


@pytest.mark.anyio
async def test_send_notification_exception_returns_false() -> None:
    """전송 중 예외 발생 → False (fire-and-forget)."""
    svc = _make_service(enabled=True)
    with patch.object(asyncio, "to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.side_effect = Exception("Firebase error")
        result = await svc.send_notification("token123", "제목", "본문")
    assert result is False


# ── send_silent ───────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_silent_disabled_returns_false() -> None:
    """FCM 비활성 → False 반환."""
    svc = _make_service(enabled=False)
    result = await svc.send_silent("token123", {"type": "badge_update"})
    assert result is False


@pytest.mark.anyio
async def test_send_silent_enabled_success_returns_true() -> None:
    """FCM 활성 + silent 전송 성공 → True."""
    svc = _make_service(enabled=True)
    with patch.object(asyncio, "to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = "msg_id"
        result = await svc.send_silent(
            "token123", {"type": "badge_update", "count": "5"}
        )
    assert result is True


@pytest.mark.anyio
async def test_send_silent_exception_returns_false() -> None:
    """silent 전송 예외 → False."""
    svc = _make_service(enabled=True)
    with patch.object(asyncio, "to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.side_effect = RuntimeError("timeout")
        result = await svc.send_silent("token123", {"type": "badge_update"})
    assert result is False


# ── send_multicast ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_multicast_disabled_returns_zero() -> None:
    """FCM 비활성 → (0, []) 반환."""
    svc = _make_service(enabled=False)
    count, failed = await svc.send_multicast(["tok1", "tok2"], "제목", "본문")
    assert count == 0
    assert failed == []


@pytest.mark.anyio
async def test_send_multicast_empty_tokens_returns_zero() -> None:
    """빈 토큰 리스트 → (0, []) 반환 (활성화 여부 무관)."""
    svc = _make_service(enabled=True)
    count, failed = await svc.send_multicast([], "제목", "본문")
    assert count == 0
    assert failed == []


@pytest.mark.anyio
async def test_send_multicast_returns_success_count() -> None:
    """멀티캐스트 발송 → success_count 반환."""
    svc = _make_service(enabled=True)
    mock_response = MagicMock()
    mock_response.success_count = 2
    resp1 = MagicMock()
    resp1.success = True
    resp2 = MagicMock()
    resp2.success = True
    mock_response.responses = [resp1, resp2]

    with patch.object(asyncio, "to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = mock_response
        count, failed = await svc.send_multicast(["tok1", "tok2"], "제목", "본문")
    assert count == 2
    assert failed == []


@pytest.mark.anyio
async def test_send_multicast_invalid_token_returned_in_failed_tokens() -> None:
    """NotRegistered 오류 코드 → failed_tokens에 해당 토큰 포함."""
    svc = _make_service(enabled=True)
    mock_response = MagicMock()
    mock_response.success_count = 1
    resp_ok = MagicMock()
    resp_ok.success = True
    resp_fail = MagicMock()
    resp_fail.success = False
    resp_fail.exception.code = "registration-token-not-registered"
    mock_response.responses = [resp_ok, resp_fail]

    with patch.object(asyncio, "to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = mock_response
        count, failed = await svc.send_multicast(["tok_ok", "tok_bad"], "제목", "본문")

    assert count == 1
    assert failed == ["tok_bad"]


@pytest.mark.anyio
async def test_send_multicast_exception_returns_zero() -> None:
    """멀티캐스트 예외 → 0 반환."""
    svc = _make_service(enabled=True)
    with patch.object(asyncio, "to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.side_effect = Exception("Firebase timeout")
        count, failed = await svc.send_multicast(["tok1", "tok2"], "제목", "본문")
    assert count == 0
    assert failed == []


# ── send_price_alert (하위 호환) ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_price_alert_delegates_to_send_notification() -> None:
    """send_price_alert() → send_notification() 위임 확인 (v1-21 하위 호환)."""
    svc = _make_service(enabled=True)
    svc.send_notification = AsyncMock(return_value=True)

    result = await svc.send_price_alert(
        fcm_token="tok1",
        coin_symbol="BTC/KRW",
        condition="above",
        target_price=Decimal("85000000"),
        current_price=Decimal("85100000"),
    )

    assert result is True
    svc.send_notification.assert_called_once()
    # title에 코인 심볼 포함 확인
    call_args = svc.send_notification.call_args.args
    assert "BTC/KRW" in call_args[1]
    # data에 type=price_alert 포함 확인
    data_arg = call_args[3]
    assert data_arg["type"] == "price_alert"
    assert data_arg["condition"] == "above"
