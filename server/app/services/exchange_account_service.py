"""거래소 계정 관리 서비스 — 등록/조회/수정/삭제/검증."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.encryption import decrypt_value, encrypt_value
from app.core.exceptions import ExchangeErrors
from app.models.exchange import UserExchangeAccount
from app.providers.enums import ExchangeType
from app.providers.exceptions import ExchangeNetworkError, ExchangeUnavailableError
from app.providers.types import ApiKeyInfo
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.schemas.exchange import ExchangeAccountResponse, ExchangeVerifyResponse, mask_api_key

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.providers.base import ExchangeProvider
    from app.providers.factory import ExchangeProviderFactory

logger = logging.getLogger(__name__)


class ExchangeAccountService:
    """거래소 API 키 CRUD + 검증 비즈니스 로직."""

    def __init__(
        self,
        repo: ExchangeAccountRepository,
        factory: ExchangeProviderFactory,
        settings: Settings,
    ) -> None:
        self._repo = repo
        self._factory = factory
        self._settings = settings

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _get_encryption_key(self) -> bytes:
        """EXCHANGE_API_KEY_SECRET → 32바이트 AES 키 반환.

        Raises:
            AppError(EXCHANGE_ENCRYPTION_NOT_CONFIGURED): 키 미설정.
        """
        secret = self._settings.EXCHANGE_API_KEY_SECRET
        if not secret:
            raise ExchangeErrors.encryption_key_not_configured()
        return bytes.fromhex(secret)

    def _build_response(
        self, account: UserExchangeAccount, api_key_plaintext: str
    ) -> ExchangeAccountResponse:
        """UserExchangeAccount → ExchangeAccountResponse 변환 (마스킹 포함)."""
        return ExchangeAccountResponse(
            id=account.id,
            exchange_type=account.exchange_type,
            nickname=account.nickname,
            api_key_masked=mask_api_key(api_key_plaintext),
            permissions=account.permissions,
            is_active=account.is_active,
            is_verified=account.is_verified,
            warning_level=account.warning_level,
            verified_at=account.verified_at,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def register(
        self,
        user_id: uuid.UUID,
        exchange_type: ExchangeType,
        api_key: str,
        api_secret: str,
        nickname: str | None = None,
    ) -> ExchangeAccountResponse:
        """거래소 API 키 등록.

        Raises:
            AppError(EXCHANGE_ENCRYPTION_NOT_CONFIGURED): 암호화 키 미설정.
            AppError(EXCHANGE_DUPLICATE_ACCOUNT): 이미 등록된 계정.
            AppError(EXCHANGE_INVALID_API_KEY): API 키 검증 실패.
            AppError(EXCHANGE_UNAVAILABLE): 거래소 연결 불가.
        """
        enc_key = self._get_encryption_key()

        # 중복 확인
        existing = await self._repo.get_by_user_and_exchange(
            user_id, exchange_type.value
        )
        if existing is not None:
            raise ExchangeErrors.duplicate_exchange_account(exchange_type.value)

        # API 키 검증
        api_key_info = await self._verify_with_provider(
            exchange_type, api_key, api_secret, str(user_id)
        )
        if not api_key_info.is_valid:
            raise ExchangeErrors.invalid_api_key()

        warning_level = "warning" if api_key_info.has_withdraw_permission else "none"
        permissions = [p.value for p in api_key_info.permissions]

        # 암호화 후 저장
        api_key_enc = encrypt_value(api_key, enc_key)
        api_secret_enc = encrypt_value(api_secret, enc_key)

        account = await self._repo.create(
            user_id=user_id,
            exchange_type=exchange_type.value,
            api_key_encrypted=api_key_enc,
            api_secret_encrypted=api_secret_enc,
            permissions=permissions,
            nickname=nickname,
            is_verified=True,
            warning_level=warning_level,
            verified_at=datetime.now(UTC),
        )
        return self._build_response(account, api_key)

    async def list_accounts(self, user_id: uuid.UUID) -> list[ExchangeAccountResponse]:
        """사용자의 등록된 거래소 계정 목록 반환."""
        enc_key = self._get_encryption_key()
        accounts = await self._repo.get_by_user_id(user_id)
        result = []
        for account in accounts:
            api_key_plain = decrypt_value(account.api_key_encrypted, enc_key)
            result.append(self._build_response(account, api_key_plain))
        return result

    async def update(
        self,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        api_key: str | None = None,
        api_secret: str | None = None,
        nickname: str | None = None,
    ) -> ExchangeAccountResponse:
        """거래소 계정 수정.

        Raises:
            AppError(EXCHANGE_ACCOUNT_NOT_FOUND): 계정 없음 또는 타 사용자 소유.
            AppError(EXCHANGE_KEY_PAIR_REQUIRED): api_key/api_secret 중 하나만 제공.
            AppError(EXCHANGE_INVALID_API_KEY): 새 API 키 검증 실패.
        """
        account = await self._repo.get_by_id(account_id)
        if account is None or account.user_id != user_id:
            raise ExchangeErrors.account_not_found()

        # api_key / api_secret 중 하나만 제공된 경우 거부
        key_provided = api_key is not None
        secret_provided = api_secret is not None
        if key_provided != secret_provided:
            raise ExchangeErrors.key_pair_required()

        kwargs: dict[str, object] = {}

        if key_provided and secret_provided:
            enc_key = self._get_encryption_key()
            exchange_type = ExchangeType(account.exchange_type)

            api_key_info = await self._verify_with_provider(
                exchange_type, api_key, api_secret, str(user_id)  # type: ignore[arg-type]
            )
            if not api_key_info.is_valid:
                raise ExchangeErrors.invalid_api_key()

            warning_level = "warning" if api_key_info.has_withdraw_permission else "none"
            permissions = [p.value for p in api_key_info.permissions]

            kwargs["api_key_encrypted"] = encrypt_value(api_key, enc_key)  # type: ignore[arg-type]
            kwargs["api_secret_encrypted"] = encrypt_value(api_secret, enc_key)  # type: ignore[arg-type]
            kwargs["permissions"] = permissions
            kwargs["is_verified"] = True
            kwargs["warning_level"] = warning_level
            kwargs["verified_at"] = datetime.now(UTC)

        if nickname is not None:
            kwargs["nickname"] = nickname

        updated = await self._repo.update(account_id, **kwargs)

        # 최신 api_key 평문 확보 (변경된 경우 제공된 값, 아니면 복호화)
        if api_key is not None:
            api_key_plain = api_key
        else:
            enc_key = self._get_encryption_key()
            api_key_plain = decrypt_value(updated.api_key_encrypted, enc_key)

        return self._build_response(updated, api_key_plain)

    async def delete(self, user_id: uuid.UUID, account_id: uuid.UUID) -> None:
        """거래소 계정 삭제.

        Raises:
            AppError(EXCHANGE_ACCOUNT_NOT_FOUND): 계정 없음 또는 타 사용자 소유.
        """
        account = await self._repo.get_by_id(account_id)
        if account is None or account.user_id != user_id:
            raise ExchangeErrors.account_not_found()
        await self._repo.delete(account_id)

    async def verify(
        self, user_id: uuid.UUID, account_id: uuid.UUID
    ) -> ExchangeVerifyResponse:
        """저장된 API 키로 거래소 연결 검증 후 결과 저장.

        Raises:
            AppError(EXCHANGE_ACCOUNT_NOT_FOUND): 계정 없음 또는 타 사용자 소유.
            AppError(EXCHANGE_ENCRYPTION_NOT_CONFIGURED): 암호화 키 미설정.
            AppError(EXCHANGE_UNAVAILABLE): 거래소 연결 불가.
        """
        account = await self._repo.get_by_id(account_id)
        if account is None or account.user_id != user_id:
            raise ExchangeErrors.account_not_found()

        enc_key = self._get_encryption_key()
        api_key = decrypt_value(account.api_key_encrypted, enc_key)
        api_secret = decrypt_value(account.api_secret_encrypted, enc_key)
        exchange_type = ExchangeType(account.exchange_type)

        api_key_info = await self._verify_with_provider(
            exchange_type, api_key, api_secret, str(user_id)
        )

        warning_level = "none"
        if api_key_info.is_valid and api_key_info.has_withdraw_permission:
            warning_level = "warning"
        elif not api_key_info.is_valid:
            warning_level = account.warning_level

        permissions = [p.value for p in api_key_info.permissions]

        await self._repo.update(
            account_id,
            is_verified=api_key_info.is_valid,
            permissions=permissions,
            warning_level=warning_level,
            verified_at=datetime.now(UTC),
        )

        return ExchangeVerifyResponse(
            is_valid=api_key_info.is_valid,
            permissions=permissions,
            has_withdraw_permission=api_key_info.has_withdraw_permission,
            warning_level=warning_level,
            message=api_key_info.error_message,
        )

    # ── 내부 검증 헬퍼 ────────────────────────────────────────────────────────

    async def _verify_with_provider(
        self,
        exchange_type: ExchangeType,
        api_key: str,
        api_secret: str,
        user_id: str,
    ) -> ApiKeyInfo:
        """ExchangeProviderFactory를 통해 API 키 유효성 검증.

        Raises:
            AppError(EXCHANGE_UNAVAILABLE): 네트워크 오류 또는 서킷 오픈.
        """
        provider: ExchangeProvider | None = None
        try:
            provider = self._factory.create(
                exchange_type=exchange_type,
                api_key=api_key,
                api_secret=api_secret,
                user_id=user_id,
            )
            return await provider.verify_api_key()
        except (ExchangeNetworkError, ExchangeUnavailableError) as exc:
            logger.warning("Exchange unavailable during verify: %s", exc)
            raise ExchangeErrors.unavailable(exchange_type.value)
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass
