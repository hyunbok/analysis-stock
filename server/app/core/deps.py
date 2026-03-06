import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings as _settings
from app.core.database import get_db
from app.core.exceptions import AuthErrors
from app.core.mongodb import get_mongodb
from app.core.rate_limiter import APIRateLimiter, ExchangeRateLimiter
from app.core.redis import get_redis, get_pubsub_redis
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.client_repository import ClientRepository
from app.repositories.user_repository import UserRepository
from app.repositories.social_account_repository import SocialAccountRepository
from app.services.audit_service import AuditService
from app.services.auth_cache_service import AuthCacheService
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.services.jwks_cache_service import JwksCacheService
from app.services.oauth_verification_service import OAuthVerificationService
from app.services.session_service import SessionService
from app.services.social_auth_service import SocialAuthService
from app.services.two_factor_service import TwoFactorService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_api_rate_limiter(redis: Redis = Depends(get_redis)) -> APIRateLimiter:
    return APIRateLimiter(redis)


def get_exchange_rate_limiter(redis: Redis = Depends(get_redis)) -> ExchangeRateLimiter:
    return ExchangeRateLimiter(redis)


def get_settings() -> Settings:
    return _settings


def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_email_service(settings: Settings = Depends(get_settings)) -> EmailService:
    return EmailService(settings)


def get_auth_cache_service(redis: Redis = Depends(get_redis)) -> AuthCacheService:
    return AuthCacheService(redis)


def get_auth_service(
    user_repo: UserRepository = Depends(get_user_repository),
    auth_cache: AuthCacheService = Depends(get_auth_cache_service),
    email_svc: EmailService = Depends(get_email_service),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(user_repo, auth_cache, email_svc, settings)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Bearer JWT 검증 → User 반환.

    Raises:
        AppError(UNAUTHORIZED): 토큰 없음/만료/변조.
        AppError(ACCOUNT_DELETED): 삭제 예약된 계정.
        AppError(EMAIL_NOT_VERIFIED): 이메일 미인증.
    """
    if not token:
        raise AuthErrors.unauthorized()

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise AuthErrors.unauthorized()

    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        raise AuthErrors.unauthorized()

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise AuthErrors.unauthorized()

    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise AuthErrors.unauthorized()

    if user.soft_deleted_at is not None:
        raise AuthErrors.account_deleted()

    if user.email_verified_at is None:
        raise AuthErrors.email_not_verified()

    return user


async def get_current_client_id(
    token: str | None = Depends(oauth2_scheme),
) -> uuid.UUID | None:
    """Access JWT payload에서 client_id 추출.

    Returns:
        client_id UUID 또는 None (토큰 없음 / payload에 미포함).
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except JWTError:
        return None
    client_id_str: str | None = payload.get("client_id")
    if not client_id_str:
        return None
    try:
        return uuid.UUID(client_id_str)
    except ValueError:
        return None


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """인증 선택적 — 토큰 없으면 None 반환."""
    auth_header: str | None = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except JWTError:
        return None

    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        return None

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        return None

    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if user is None or user.soft_deleted_at is not None:
        return None

    return user


def get_client_repository(db: AsyncSession = Depends(get_db)) -> ClientRepository:
    return ClientRepository(db)


def get_two_factor_service(
    user_repo: UserRepository = Depends(get_user_repository),
    cache: AuthCacheService = Depends(get_auth_cache_service),
    settings: Settings = Depends(get_settings),
) -> TwoFactorService:
    return TwoFactorService(user_repo, cache, settings)


def get_session_service(
    client_repo: ClientRepository = Depends(get_client_repository),
    cache: AuthCacheService = Depends(get_auth_cache_service),
) -> SessionService:
    return SessionService(client_repo, cache)


def get_audit_service(
    mongodb: AsyncIOMotorDatabase = Depends(get_mongodb),
) -> AuditService:
    return AuditService(mongodb)


def get_social_account_repository(
    db: AsyncSession = Depends(get_db),
) -> SocialAccountRepository:
    return SocialAccountRepository(db)


def get_jwks_cache_service(
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> JwksCacheService:
    return JwksCacheService(redis, settings)


def get_oauth_verification_service(
    jwks_cache: JwksCacheService = Depends(get_jwks_cache_service),
    settings: Settings = Depends(get_settings),
) -> OAuthVerificationService:
    return OAuthVerificationService(settings, jwks_cache)


def get_social_auth_service(
    user_repo: UserRepository = Depends(get_user_repository),
    social_repo: SocialAccountRepository = Depends(get_social_account_repository),
    cache: AuthCacheService = Depends(get_auth_cache_service),
    settings: Settings = Depends(get_settings),
) -> SocialAuthService:
    return SocialAuthService(user_repo, social_repo, cache, settings)


# ── Type aliases ──────────────────────────────────────────────────────────────

DbSession = Annotated[AsyncSession, Depends(get_db)]
MongoDb = Annotated[AsyncIOMotorDatabase, Depends(get_mongodb)]
RedisClient = Annotated[Redis, Depends(get_redis)]
PubSubRedisClient = Annotated[Redis, Depends(get_pubsub_redis)]
ApiRateLimiter = Annotated[APIRateLimiter, Depends(get_api_rate_limiter)]
ExchangeLimiter = Annotated[ExchangeRateLimiter, Depends(get_exchange_rate_limiter)]
AppSettings = Annotated[Settings, Depends(get_settings)]

CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SocialAuthServiceDep = Annotated[SocialAuthService, Depends(get_social_auth_service)]
OAuthVerificationServiceDep = Annotated[OAuthVerificationService, Depends(get_oauth_verification_service)]
ClientRepoDep = Annotated[ClientRepository, Depends(get_client_repository)]
TwoFactorServiceDep = Annotated[TwoFactorService, Depends(get_two_factor_service)]
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
CurrentClientId = Annotated[uuid.UUID | None, Depends(get_current_client_id)]
