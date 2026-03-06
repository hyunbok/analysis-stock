"""Audit Logging 서비스 — 인증 이벤트를 MongoDB audit_logs에 기록."""
from __future__ import annotations

import logging
import uuid

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.documents.audit_logs import AuditLog

logger = logging.getLogger(__name__)


class AuditAction:
    """Audit Log action 상수."""

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    PASSWORD_CHANGE = "password_change"
    TWO_FACTOR_ENABLED = "2fa_enabled"
    TWO_FACTOR_DISABLED = "2fa_disabled"
    TWO_FACTOR_LOGIN_SUCCESS = "2fa_login_success"
    TWO_FACTOR_LOGIN_FAILED = "2fa_login_failed"
    TWO_FACTOR_BACKUP_USED = "2fa_backup_used"
    NEW_DEVICE_LOGIN = "new_device_login"
    SESSION_REVOKED = "session_revoked"


class AuditService:
    """인증 이벤트 Audit Log 기록 서비스.

    MongoDB audit_logs 컬렉션에 비동기로 기록한다.
    실패해도 주요 비즈니스 플로우를 차단하지 않는다 (fire-and-forget).
    """

    def __init__(self, mongodb: AsyncIOMotorDatabase) -> None:
        self._db = mongodb

    async def log(
        self,
        action: str,
        ip_address: str,
        user_agent: str,
        user_id: uuid.UUID | None = None,
        details: dict | None = None,
    ) -> None:
        """Audit Log 기록.

        Args:
            action: AuditAction 상수 중 하나.
            ip_address: 요청 클라이언트 IP.
            user_agent: HTTP User-Agent 헤더값.
            user_id: 사용자 UUID (로그인 실패 등 미인증 이벤트는 None).
            details: 추가 컨텍스트 딕셔너리 (선택).
        """
        try:
            audit = AuditLog(
                user_id=user_id,
                action=action,
                ip_address=ip_address,
                user_agent=user_agent,
                details=details,
            )
            await audit.insert()
        except Exception:
            logger.error(
                "audit_log_failed",
                extra={"action": action, "user_id": str(user_id)},
                exc_info=True,
            )
