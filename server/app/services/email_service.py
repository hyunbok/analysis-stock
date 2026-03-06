"""SMTP 이메일 발송 서비스 (aiosmtplib 기반)."""
from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import Settings
from app.core.exceptions import AuthErrors

logger = logging.getLogger(__name__)


class EmailService:
    """SMTP 이메일 발송 서비스."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_verification_code(self, to_email: str, code: str) -> None:
        """6자리 인증 코드 발송.

        Args:
            to_email: 수신자 이메일 주소.
            code: 6자리 숫자 인증 코드.

        Raises:
            AppError(EMAIL_SEND_FAILED): SMTP 연결 또는 발송 실패 시.
        """
        s = self._settings
        message = EmailMessage()
        message["From"] = f"{s.SMTP_FROM_NAME} <{s.SMTP_FROM_EMAIL}>"
        message["To"] = to_email
        message["Subject"] = "[CoinTrader] 이메일 인증 코드"
        message.set_content(
            f"CoinTrader 인증 코드: {code}\n\n"
            f"이 코드는 10분 동안 유효합니다.\n"
            f"본인이 요청하지 않은 경우 이 메일을 무시하세요."
        )

        try:
            await aiosmtplib.send(
                message,
                hostname=s.SMTP_HOST,
                port=s.SMTP_PORT,
                username=s.SMTP_USER or None,
                password=s.SMTP_PASSWORD or None,
                start_tls=s.SMTP_STARTTLS,
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            masked = to_email[:3] + "***" + to_email[to_email.find("@"):]
            logger.error("smtp_send_failed", to=masked, error=type(exc).__name__)
            raise AuthErrors.email_send_failed() from exc
