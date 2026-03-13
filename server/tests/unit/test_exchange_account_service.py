"""ExchangeAccountService 단위 테스트."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppError
from app.providers.enums import ApiKeyPermission, ExchangeType
from app.providers.types import ApiKeyInfo
from app.schemas.exchange import mask_api_key
from app.services.exchange_account_service import ExchangeAccountService

# ── 테스트용 상수 ─────────────────────────────────────────────────────────────

VALID_SECRET = "a" * 64  # 64자 hex (모두 'a' — 유효한 hex)
USER_ID = uuid.uuid4()
ACCOUNT_ID = uuid.uuid4()
EXCHANGE_TYPE = ExchangeType.UPBIT
API_KEY = "test-api-key-abcdef123456"
API_SECRET = "test-api-secret-xyz"


# ── Fixture ───────────────────────────────────────────────────────────────────


def make_settings(secret: str = VALID_SECRET) -> MagicMock:
    settings = MagicMock()
    settings.EXCHANGE_API_KEY_SECRET = secret
    return settings


def make_api_key_info(
    is_valid: bool = True,
    has_withdraw: bool = False,
    permissions: list[ApiKeyPermission] | None = None,
    error_message: str | None = None,
) -> ApiKeyInfo:
    return ApiKeyInfo(
        exchange=EXCHANGE_TYPE,
        permissions=permissions or [ApiKeyPermission.VIEW_BALANCE, ApiKeyPermission.TRADE],
        is_valid=is_valid,
        error_message=error_message,
        has_withdraw_permission=has_withdraw,
    )


def make_account(
    account_id: uuid.UUID = ACCOUNT_ID,
    user_id: uuid.UUID = USER_ID,
    exchange_type: str = "upbit",
    api_key_encrypted: bytes = b"encrypted_key",
    api_secret_encrypted: bytes = b"encrypted_secret",
    permissions: list[str] | None = None,
    nickname: str | None = None,
    is_active: bool = True,
    is_verified: bool = True,
    warning_level: str = "none",
    verified_at: datetime | None = None,
) -> MagicMock:
    account = MagicMock()
    account.id = account_id
    account.user_id = user_id
    account.exchange_type = exchange_type
    account.api_key_encrypted = api_key_encrypted
    account.api_secret_encrypted = api_secret_encrypted
    account.permissions = permissions or ["view_balance", "trade"]
    account.nickname = nickname
    account.is_active = is_active
    account.is_verified = is_verified
    account.warning_level = warning_level
    account.verified_at = verified_at or datetime.now(UTC)
    account.created_at = datetime.now(UTC)
    account.updated_at = datetime.now(UTC)
    return account


def make_service(
    repo: MagicMock | None = None,
    factory: MagicMock | None = None,
    settings: MagicMock | None = None,
) -> ExchangeAccountService:
    return ExchangeAccountService(
        repo=repo or MagicMock(),
        factory=factory or MagicMock(),
        settings=settings or make_settings(),
    )


# ── mask_api_key 테스트 ────────────────────────────────────────────────────────


def test_mask_api_key_long():
    assert mask_api_key("abcdef123456") == "****123456"


def test_mask_api_key_exactly_6():
    assert mask_api_key("abc123") == "****"


def test_mask_api_key_short():
    assert mask_api_key("abc") == "****"


def test_mask_api_key_7_chars():
    assert mask_api_key("abcd123") == "****bcd123"


# ── 암호화 키 설정 검증 ────────────────────────────────────────────────────────


def test_get_encryption_key_not_configured():
    svc = make_service(settings=make_settings(secret=""))
    with pytest.raises(AppError) as exc_info:
        svc._get_encryption_key()
    assert exc_info.value.code == "EXCHANGE_ENCRYPTION_NOT_CONFIGURED"
    assert exc_info.value.http_status == 500


def test_get_encryption_key_success():
    svc = make_service()
    key = svc._get_encryption_key()
    assert isinstance(key, bytes)
    assert len(key) == 32


# ── register ──────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_register_success():
    repo = MagicMock()
    repo.get_by_user_and_exchange = AsyncMock(return_value=None)
    account = make_account()
    repo.create = AsyncMock(return_value=account)

    provider = AsyncMock()
    provider.verify_api_key = AsyncMock(return_value=make_api_key_info())
    provider.close = AsyncMock()

    factory = MagicMock()
    factory.create = MagicMock(return_value=provider)

    svc = make_service(repo=repo, factory=factory)
    response = await svc.register(
        user_id=USER_ID,
        exchange_type=EXCHANGE_TYPE,
        api_key=API_KEY,
        api_secret=API_SECRET,
    )

    assert response.is_verified is True
    assert response.warning_level == "none"
    assert response.api_key_masked == mask_api_key(API_KEY)
    repo.create.assert_called_once()


@pytest.mark.anyio
async def test_register_duplicate_account():
    repo = MagicMock()
    repo.get_by_user_and_exchange = AsyncMock(return_value=make_account())

    svc = make_service(repo=repo)
    with pytest.raises(AppError) as exc_info:
        await svc.register(
            user_id=USER_ID,
            exchange_type=EXCHANGE_TYPE,
            api_key=API_KEY,
            api_secret=API_SECRET,
        )
    assert exc_info.value.code == "EXCHANGE_DUPLICATE_ACCOUNT"
    assert exc_info.value.http_status == 409


@pytest.mark.anyio
async def test_register_invalid_api_key():
    repo = MagicMock()
    repo.get_by_user_and_exchange = AsyncMock(return_value=None)

    provider = AsyncMock()
    provider.verify_api_key = AsyncMock(
        return_value=make_api_key_info(is_valid=False, error_message="Invalid key")
    )
    provider.close = AsyncMock()

    factory = MagicMock()
    factory.create = MagicMock(return_value=provider)

    svc = make_service(repo=repo, factory=factory)
    with pytest.raises(AppError) as exc_info:
        await svc.register(
            user_id=USER_ID,
            exchange_type=EXCHANGE_TYPE,
            api_key=API_KEY,
            api_secret=API_SECRET,
        )
    assert exc_info.value.code == "EXCHANGE_INVALID_API_KEY"


@pytest.mark.anyio
async def test_register_withdraw_permission_warning():
    repo = MagicMock()
    repo.get_by_user_and_exchange = AsyncMock(return_value=None)
    account = make_account(warning_level="warning")
    repo.create = AsyncMock(return_value=account)

    provider = AsyncMock()
    provider.verify_api_key = AsyncMock(
        return_value=make_api_key_info(has_withdraw=True)
    )
    provider.close = AsyncMock()

    factory = MagicMock()
    factory.create = MagicMock(return_value=provider)

    svc = make_service(repo=repo, factory=factory)
    response = await svc.register(
        user_id=USER_ID,
        exchange_type=EXCHANGE_TYPE,
        api_key=API_KEY,
        api_secret=API_SECRET,
    )
    # warning_level은 계정 객체에서 읽어오므로 mock 값 확인
    assert response.warning_level == "warning"


# ── list_accounts ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_accounts_returns_masked():
    from app.core.encryption import encrypt_value

    enc_key = bytes.fromhex(VALID_SECRET)
    encrypted_key = encrypt_value(API_KEY, enc_key)

    account = make_account(api_key_encrypted=encrypted_key)
    repo = MagicMock()
    repo.get_by_user_id = AsyncMock(return_value=[account])

    svc = make_service(repo=repo)
    result = await svc.list_accounts(user_id=USER_ID)

    assert len(result) == 1
    assert result[0].api_key_masked == mask_api_key(API_KEY)


@pytest.mark.anyio
async def test_list_accounts_empty():
    repo = MagicMock()
    repo.get_by_user_id = AsyncMock(return_value=[])

    svc = make_service(repo=repo)
    result = await svc.list_accounts(user_id=USER_ID)
    assert result == []


# ── update ────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_update_nickname_only():
    from app.core.encryption import encrypt_value

    enc_key = bytes.fromhex(VALID_SECRET)
    encrypted_key = encrypt_value(API_KEY, enc_key)

    account = make_account(api_key_encrypted=encrypted_key, nickname="old")
    updated_account = make_account(api_key_encrypted=encrypted_key, nickname="new")

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=account)
    repo.update = AsyncMock(return_value=updated_account)

    svc = make_service(repo=repo)
    response = await svc.update(
        user_id=USER_ID, account_id=ACCOUNT_ID, nickname="new"
    )
    assert response.nickname == "new"


@pytest.mark.anyio
async def test_update_key_pair_required():
    account = make_account()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=account)

    svc = make_service(repo=repo)
    with pytest.raises(AppError) as exc_info:
        await svc.update(
            user_id=USER_ID,
            account_id=ACCOUNT_ID,
            api_key="only-key",  # secret 미제공
        )
    assert exc_info.value.code == "EXCHANGE_KEY_PAIR_REQUIRED"


@pytest.mark.anyio
async def test_update_ownership_check():
    other_user = uuid.uuid4()
    account = make_account(user_id=other_user)

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=account)

    svc = make_service(repo=repo)
    with pytest.raises(AppError) as exc_info:
        await svc.update(user_id=USER_ID, account_id=ACCOUNT_ID, nickname="new")
    assert exc_info.value.code == "EXCHANGE_ACCOUNT_NOT_FOUND"


# ── delete ────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_success():
    account = make_account()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=account)
    repo.delete = AsyncMock()

    svc = make_service(repo=repo)
    await svc.delete(user_id=USER_ID, account_id=ACCOUNT_ID)
    repo.delete.assert_called_once_with(ACCOUNT_ID)


@pytest.mark.anyio
async def test_delete_not_found():
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=None)

    svc = make_service(repo=repo)
    with pytest.raises(AppError) as exc_info:
        await svc.delete(user_id=USER_ID, account_id=ACCOUNT_ID)
    assert exc_info.value.code == "EXCHANGE_ACCOUNT_NOT_FOUND"


@pytest.mark.anyio
async def test_delete_ownership_check():
    other_user = uuid.uuid4()
    account = make_account(user_id=other_user)

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=account)

    svc = make_service(repo=repo)
    with pytest.raises(AppError) as exc_info:
        await svc.delete(user_id=USER_ID, account_id=ACCOUNT_ID)
    assert exc_info.value.code == "EXCHANGE_ACCOUNT_NOT_FOUND"


# ── verify ────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_verify_success():
    from app.core.encryption import encrypt_value

    enc_key = bytes.fromhex(VALID_SECRET)
    encrypted_key = encrypt_value(API_KEY, enc_key)
    encrypted_secret = encrypt_value(API_SECRET, enc_key)

    account = make_account(
        api_key_encrypted=encrypted_key, api_secret_encrypted=encrypted_secret
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=account)
    repo.update = AsyncMock(return_value=account)

    provider = AsyncMock()
    provider.verify_api_key = AsyncMock(return_value=make_api_key_info())
    provider.close = AsyncMock()

    factory = MagicMock()
    factory.create = MagicMock(return_value=provider)

    svc = make_service(repo=repo, factory=factory)
    result = await svc.verify(user_id=USER_ID, account_id=ACCOUNT_ID)

    assert result.is_valid is True
    assert result.warning_level == "none"
    repo.update.assert_called_once()


@pytest.mark.anyio
async def test_verify_not_found():
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=None)

    svc = make_service(repo=repo)
    with pytest.raises(AppError) as exc_info:
        await svc.verify(user_id=USER_ID, account_id=ACCOUNT_ID)
    assert exc_info.value.code == "EXCHANGE_ACCOUNT_NOT_FOUND"


@pytest.mark.anyio
async def test_verify_unavailable_exchange():
    from app.core.encryption import encrypt_value
    from app.providers.exceptions import ExchangeNetworkError

    enc_key = bytes.fromhex(VALID_SECRET)
    account = make_account(
        api_key_encrypted=encrypt_value(API_KEY, enc_key),
        api_secret_encrypted=encrypt_value(API_SECRET, enc_key),
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=account)

    provider = AsyncMock()
    provider.verify_api_key = AsyncMock(
        side_effect=ExchangeNetworkError("upbit", "Connection timeout")
    )
    provider.close = AsyncMock()

    factory = MagicMock()
    factory.create = MagicMock(return_value=provider)

    svc = make_service(repo=repo, factory=factory)
    with pytest.raises(AppError) as exc_info:
        await svc.verify(user_id=USER_ID, account_id=ACCOUNT_ID)
    assert exc_info.value.code == "EXCHANGE_UNAVAILABLE"


@pytest.mark.anyio
async def test_verify_invalid_key_updates_db():
    """verify() 호출 시 is_valid=False도 DB를 업데이트해야 한다."""
    from app.core.encryption import encrypt_value

    enc_key = bytes.fromhex(VALID_SECRET)
    account = make_account(
        api_key_encrypted=encrypt_value(API_KEY, enc_key),
        api_secret_encrypted=encrypt_value(API_SECRET, enc_key),
        warning_level="none",
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=account)
    repo.update = AsyncMock(return_value=account)

    provider = AsyncMock()
    provider.verify_api_key = AsyncMock(
        return_value=make_api_key_info(is_valid=False, error_message="키 만료")
    )
    provider.close = AsyncMock()

    factory = MagicMock()
    factory.create = MagicMock(return_value=provider)

    svc = make_service(repo=repo, factory=factory)
    result = await svc.verify(user_id=USER_ID, account_id=ACCOUNT_ID)

    assert result.is_valid is False
    repo.update.assert_called_once()
    update_kwargs = repo.update.call_args.kwargs
    assert update_kwargs["is_verified"] is False


@pytest.mark.anyio
async def test_update_key_pair_success():
    """api_key + api_secret 쌍을 동시에 변경하면 성공해야 한다."""
    from app.core.encryption import encrypt_value

    enc_key = bytes.fromhex(VALID_SECRET)
    new_key = "new-api-key-abcdef123456"
    new_secret = "new-api-secret-xyz"

    account = make_account(
        api_key_encrypted=encrypt_value(API_KEY, enc_key),
        api_secret_encrypted=encrypt_value(API_SECRET, enc_key),
    )
    updated_account = make_account(
        api_key_encrypted=encrypt_value(new_key, enc_key),
        api_secret_encrypted=encrypt_value(new_secret, enc_key),
    )

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=account)
    repo.update = AsyncMock(return_value=updated_account)

    provider = AsyncMock()
    provider.verify_api_key = AsyncMock(return_value=make_api_key_info())
    provider.close = AsyncMock()

    factory = MagicMock()
    factory.create = MagicMock(return_value=provider)

    svc = make_service(repo=repo, factory=factory)
    response = await svc.update(
        user_id=USER_ID,
        account_id=ACCOUNT_ID,
        api_key=new_key,
        api_secret=new_secret,
    )

    assert response.api_key_masked == mask_api_key(new_key)
    assert response.is_verified is True
    repo.update.assert_called_once()
