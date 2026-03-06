"""2FA (TOTP) 비즈니스 로직 — 설정/활성화/비활성화/검증."""
from __future__ import annotations

import base64
import io
import logging
import uuid

import pyotp
import qrcode
from cryptography.exceptions import InvalidTag

from app.core.config import Settings
from app.core.encryption import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    hash_backup_code,
)
from app.core.exceptions import AuthErrors
from app.core.redis_keys import RedisTTL
from app.repositories.user_repository import UserRepository
from app.schemas.two_factor import TwoFactorSetupResponse, TwoFactorStatusResponse
from app.services.auth_cache_service import AuthCacheService

logger = logging.getLogger(__name__)

_TOTP_ISSUER = "CoinTrader"


class TwoFactorService:
    """TOTP 2FA 설정·검증·비활성화 서비스."""

    def __init__(
        self,
        user_repo: UserRepository,
        cache: AuthCacheService,
        settings: Settings,
    ) -> None:
        self._repo = user_repo
        self._cache = cache
        self._settings = settings
        self._key = bytes.fromhex(settings.TOTP_ENCRYPTION_KEY)

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def generate_setup(
        self, user_id: uuid.UUID, email: str, is_2fa_enabled: bool
    ) -> TwoFactorSetupResponse:
        """TOTP 비밀키 생성 → Redis 임시 저장 → QR URI/이미지 반환.

        Args:
            user_id: 사용자 UUID.
            email: 사용자 이메일 (OTP URI에 포함).
            is_2fa_enabled: 현재 2FA 활성 여부 (이미 활성이면 에러).

        Returns:
            TwoFactorSetupResponse.

        Raises:
            AppError(TOTP_ALREADY_ENABLED): 이미 2FA 활성화 상태.
        """
        if is_2fa_enabled:
            raise AuthErrors.totp_already_enabled()

        secret = pyotp.random_base32()

        # Redis에 임시 secret 저장 (10분 TTL)
        await self._cache.store_2fa_setup_secret(str(user_id), secret, RedisTTL.TWO_FA_SETUP)

        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(name=email, issuer_name=_TOTP_ISSUER)

        # QR 코드 이미지 생성 (Base64 PNG)
        qr_image = qrcode.make(provisioning_uri)
        buffer = io.BytesIO()
        qr_image.save(buffer, format="PNG")
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()

        return TwoFactorSetupResponse(
            secret=secret,
            qr_code_uri=provisioning_uri,
            qr_code_base64=qr_base64,
        )

    # ── Activate ──────────────────────────────────────────────────────────────

    async def activate(self, user_id: uuid.UUID, code: str) -> list[str]:
        """Redis 임시 secret 조회 → TOTP 검증 → DB 저장 → 백업 코드 반환.

        Args:
            user_id: 사용자 UUID.
            code: 6자리 TOTP 코드.

        Returns:
            평문 백업 코드 리스트 (10개, 1회성 반환).

        Raises:
            AppError(TOTP_SETUP_REQUIRED): setup 세션 없음 또는 만료.
            AppError(INVALID_TOTP_CODE): TOTP 코드 불일치.
        """
        user_id_str = str(user_id)

        # GET (삭제 없음 — 검증 실패 시 재시도 가능하도록)
        secret = await self._cache.get_2fa_setup_secret(user_id_str)
        if secret is None:
            raise AuthErrors.totp_setup_required()

        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=1):
            raise AuthErrors.invalid_totp_code()

        # 검증 성공 후 암호화하여 DB 저장
        encrypted = encrypt_totp_secret(secret, self._key)
        await self._repo.update_totp_secret(user_id, encrypted)

        # 백업 코드 생성 및 저장
        plain_codes = generate_backup_codes(10)
        code_hashes = [hash_backup_code(c) for c in plain_codes]
        await self._repo.create_backup_codes(user_id, code_hashes)

        # 2FA 활성화
        await self._repo.set_2fa_enabled(user_id, True)

        # setup secret 삭제 (활성화 완료 후)
        await self._cache.delete_2fa_setup_secret(user_id_str)

        logger.info("2fa_activated", user_id=user_id_str)
        return plain_codes

    # ── Disable ───────────────────────────────────────────────────────────────

    async def disable(
        self, user_id: uuid.UUID, code: str, is_2fa_enabled: bool, totp_secret_encrypted: bytes | None
    ) -> None:
        """TOTP/백업 코드 검증 → 2FA 비활성화.

        Args:
            user_id: 사용자 UUID.
            code: 6자리 TOTP 또는 10자리 백업 코드.
            is_2fa_enabled: 현재 2FA 활성 여부.
            totp_secret_encrypted: DB에 저장된 암호화 secret.

        Raises:
            AppError(TOTP_NOT_ENABLED): 2FA 미활성.
            AppError(INVALID_TOTP_CODE): 코드 불일치.
        """
        if not is_2fa_enabled:
            raise AuthErrors.totp_not_enabled()

        verified = await self.verify_code(user_id, code, totp_secret_encrypted)
        if not verified:
            raise AuthErrors.invalid_totp_code()

        await self._repo.update_totp_secret(user_id, None)
        await self._repo.set_2fa_enabled(user_id, False)
        await self._repo.delete_backup_codes(user_id)

        logger.info("2fa_disabled", user_id=str(user_id))

    # ── Verify ────────────────────────────────────────────────────────────────

    async def verify_code(
        self,
        user_id: uuid.UUID,
        code: str,
        totp_secret_encrypted: bytes | None,
    ) -> bool:
        """TOTP 코드 또는 백업 코드 검증 (로그인 2단계 + disable 공용).

        브루트포스 방지:
        - `auth:2fa_fail:{user_id}` 고정 윈도우 카운터
        - 5회 초과 시 즉시 거부

        Args:
            user_id: 사용자 UUID.
            code: 6자리 TOTP 또는 10자리 백업 코드.
            totp_secret_encrypted: DB에 저장된 암호화 secret.

        Returns:
            True=검증 성공.

        Raises:
            AppError(INVALID_TOTP_CODE): 브루트포스 차단 또는 코드 불일치.
        """
        user_id_str = str(user_id)

        # 브루트포스 체크
        fail_count = await self._cache.get_2fa_fail_count(user_id_str)
        if fail_count >= self._settings.TOTP_FAIL_MAX:
            raise AuthErrors.invalid_totp_code()

        # 코드 검증 (길이 기반 자동 구분)
        success = False
        is_backup = len(code) > 6

        if is_backup:
            success = await self._verify_backup_code(user_id, code)
        else:
            if totp_secret_encrypted:
                try:
                    secret = decrypt_totp_secret(totp_secret_encrypted, self._key)
                    totp = pyotp.TOTP(secret)
                    success = totp.verify(code, valid_window=1)
                except (InvalidTag, ValueError):
                    logger.error("totp_decrypt_failed", user_id=user_id_str)
                    success = False

        if not success:
            await self._cache.increment_2fa_fail_count(user_id_str, RedisTTL.TWO_FA_FAIL)
        else:
            await self._cache.reset_2fa_fail_count(user_id_str)

        return success

    async def _verify_backup_code(self, user_id: uuid.UUID, code: str) -> bool:
        """백업 코드 검증 및 사용 처리.

        Args:
            user_id: 사용자 UUID.
            code: 10자리 백업 코드 (평문).

        Returns:
            True=유효한 미사용 백업 코드.
        """
        code_hash = hash_backup_code(code)
        backup = await self._repo.get_unused_backup_code(user_id, code_hash)
        if backup is None:
            return False

        await self._repo.mark_backup_code_used(backup.id)
        return True

    async def count_remaining_backup_codes(self, user_id: uuid.UUID) -> int:
        """미사용 백업 코드 잔여 수 조회 (AuditLog details용).

        Args:
            user_id: 사용자 UUID.

        Returns:
            미사용 코드 수 (0~10).
        """
        return await self._repo.count_unused_backup_codes(user_id)

    # ── Status ────────────────────────────────────────────────────────────────

    async def get_status(
        self, user_id: uuid.UUID, is_2fa_enabled: bool
    ) -> TwoFactorStatusResponse:
        """2FA 상태 조회.

        Args:
            user_id: 사용자 UUID.
            is_2fa_enabled: User.is_2fa_enabled.

        Returns:
            TwoFactorStatusResponse.
        """
        has_backup = False
        if is_2fa_enabled:
            count = await self._repo.count_unused_backup_codes(user_id)
            has_backup = count > 0

        return TwoFactorStatusResponse(
            is_enabled=is_2fa_enabled,
            has_backup_codes=has_backup,
        )
