"""인증 API 엔드포인트 — 회원가입, 이메일 인증, 로그인, 2FA, 세션 관리."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid

from fastapi import APIRouter, Request

from app.core.deps import (
    AuditServiceDep,
    AuthServiceDep,
    CurrentClientId,
    CurrentUser,
    SessionServiceDep,
    TwoFactorServiceDep,
)
from app.core.exceptions import AuthErrors
from app.core.redis_keys import RedisTTL
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    UserResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.schemas.common import ApiResponse
from app.schemas.session import LogoutAllResponse, SessionListResponse, SessionResponse
from app.schemas.two_factor import (
    TwoFactorActivateResponse,
    TwoFactorDisableRequest,
    TwoFactorDisableResponse,
    TwoFactorLoginVerifyRequest,
    TwoFactorSetupResponse,
    TwoFactorStatusResponse,
    TwoFactorVerifyRequest,
)
from app.services.audit_service import AuditAction
from app.services.session_service import extract_device_type

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────


def _get_ip(request: Request) -> str:
    """요청 클라이언트 IP 추출 (프록시 헤더 우선)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _get_device_info(request: Request) -> dict:
    """HTTP 헤더에서 디바이스 정보 추출."""
    user_agent = request.headers.get("User-Agent", "")
    return {
        "device_name": request.headers.get("X-Device-Name"),
        "device_fingerprint": request.headers.get("X-Device-Fingerprint"),
        "user_agent": user_agent,
        "ip_address": _get_ip(request),
        "device_type": extract_device_type(user_agent),
    }


# ── 기본 인증 ──────────────────────────────────────────────────────────────────


@router.post(
    "/register",
    response_model=ApiResponse[RegisterResponse],
    status_code=201,
    summary="회원가입",
    description="이메일, 비밀번호, 닉네임으로 가입 후 인증 코드를 이메일로 발송합니다.",
)
async def register(
    body: RegisterRequest,
    auth_svc: AuthServiceDep,
) -> ApiResponse[RegisterResponse]:
    await auth_svc.register(
        email=body.email,
        password=body.password,
        nickname=body.nickname,
    )
    return ApiResponse(data=RegisterResponse(email=body.email))


@router.post(
    "/verify-email",
    response_model=ApiResponse[VerifyEmailResponse],
    summary="이메일 인증 코드 확인",
    description="이메일로 발송된 6자리 인증 코드를 검증합니다.",
)
async def verify_email(
    body: VerifyEmailRequest,
    auth_svc: AuthServiceDep,
) -> ApiResponse[VerifyEmailResponse]:
    await auth_svc.verify_email(email=body.email, code=body.code)
    return ApiResponse(data=VerifyEmailResponse())


@router.post(
    "/login",
    response_model=ApiResponse[LoginResponse],
    summary="로그인",
    description=(
        "이메일/비밀번호 인증. "
        "2FA 비활성: user+tokens 반환. "
        "2FA 활성: requires_2fa=true + temp_token 반환 → /2fa/login-verify로 2단계 진행."
    ),
)
async def login(
    body: LoginRequest,
    request: Request,
    auth_svc: AuthServiceDep,
    session_svc: SessionServiceDep,
    audit_svc: AuditServiceDep,
) -> ApiResponse[LoginResponse]:
    device = _get_device_info(request)
    ip = device["ip_address"]
    ua = device["user_agent"]

    user = await auth_svc.verify_credentials(email=body.email, password=body.password)

    # 2FA 활성 사용자 — 임시 토큰 발급 후 2단계 진행
    if user.is_2fa_enabled:
        temp_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(temp_token.encode()).hexdigest()

        await auth_svc.store_2fa_login_pending(
            user_id=str(user.id),
            token_hash=token_hash,
            data=json.dumps({
                "user_id": str(user.id),
                "device_name": device["device_name"],
                "device_fingerprint": device["device_fingerprint"],
                "ip_address": ip,
                "user_agent": ua,
                "device_type": device["device_type"],
            }),
            ttl=RedisTTL.TWO_FA_PENDING,
        )

        return ApiResponse(
            data=LoginResponse(
                requires_2fa=True,
                temp_token=temp_token,
                temp_token_expires_in=RedisTTL.TWO_FA_PENDING,
            )
        )

    # 2FA 미활성 — 세션 생성 + 토큰 발급
    client, is_new = await session_svc.create_or_update_session(
        user_id=user.id,
        device_fingerprint=device["device_fingerprint"],
        device_name=device["device_name"],
        device_type=device["device_type"],
        ip_address=ip,
        user_agent=ua,
    )

    tokens = await auth_svc.issue_tokens_with_store(user, str(client.id))

    await audit_svc.log(
        action=AuditAction.LOGIN_SUCCESS,
        ip_address=ip,
        user_agent=ua,
        user_id=user.id,
        details={"device_name": device["device_name"], "is_new_device": is_new},
    )

    if is_new:
        await audit_svc.log(
            action=AuditAction.NEW_DEVICE_LOGIN,
            ip_address=ip,
            user_agent=ua,
            user_id=user.id,
            details={"device_name": device["device_name"], "device_fingerprint": device["device_fingerprint"]},
        )

    return ApiResponse(data=LoginResponse(user=UserResponse.from_user(user), tokens=tokens))


@router.post(
    "/refresh",
    response_model=ApiResponse[RefreshResponse],
    summary="토큰 갱신",
    description="Refresh Token으로 새 Access + Refresh 토큰 쌍을 발급합니다 (Rotation).",
)
async def refresh_tokens(
    body: RefreshRequest,
    auth_svc: AuthServiceDep,
) -> ApiResponse[RefreshResponse]:
    tokens = await auth_svc.refresh_tokens(body.refresh_token)
    return ApiResponse(data=RefreshResponse(tokens=tokens))


@router.post(
    "/logout",
    response_model=ApiResponse[LogoutResponse],
    summary="로그아웃",
    description="현재 세션의 Refresh Token을 폐기합니다.",
)
async def logout(
    body: LogoutRequest,
    request: Request,
    current_user: CurrentUser,
    auth_svc: AuthServiceDep,
    audit_svc: AuditServiceDep,
) -> ApiResponse[LogoutResponse]:
    await auth_svc.logout(
        user_id=str(current_user.id),
        refresh_token=body.refresh_token,
    )
    await audit_svc.log(
        action=AuditAction.LOGOUT,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
    )
    return ApiResponse(data=LogoutResponse())


# ── 2FA 엔드포인트 ─────────────────────────────────────────────────────────────


@router.post(
    "/2fa/setup",
    response_model=ApiResponse[TwoFactorSetupResponse],
    summary="2FA 설정 시작",
    description="TOTP 비밀키와 QR 코드를 생성합니다. 10분 내에 /2fa/verify로 활성화해야 합니다.",
)
async def two_fa_setup(
    request: Request,
    current_user: CurrentUser,
    two_factor_svc: TwoFactorServiceDep,
) -> ApiResponse[TwoFactorSetupResponse]:
    result = await two_factor_svc.generate_setup(
        user_id=current_user.id,
        email=current_user.email,
        is_2fa_enabled=current_user.is_2fa_enabled,
    )
    return ApiResponse(data=result)


@router.post(
    "/2fa/verify",
    response_model=ApiResponse[TwoFactorActivateResponse],
    summary="2FA 활성화",
    description="TOTP 코드 검증 후 2FA를 활성화하고 백업 코드를 반환합니다 (1회성).",
)
async def two_fa_verify(
    body: TwoFactorVerifyRequest,
    request: Request,
    current_user: CurrentUser,
    two_factor_svc: TwoFactorServiceDep,
    audit_svc: AuditServiceDep,
) -> ApiResponse[TwoFactorActivateResponse]:
    backup_codes = await two_factor_svc.activate(
        user_id=current_user.id,
        code=body.code,
    )

    await audit_svc.log(
        action=AuditAction.TWO_FACTOR_ENABLED,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={},
    )

    return ApiResponse(data=TwoFactorActivateResponse(backup_codes=backup_codes))


@router.post(
    "/2fa/disable",
    response_model=ApiResponse[TwoFactorDisableResponse],
    summary="2FA 비활성화",
    description="현재 TOTP 코드(6자리) 또는 백업 코드(10자리) 검증 후 2FA를 비활성화합니다.",
)
async def two_fa_disable(
    body: TwoFactorDisableRequest,
    request: Request,
    current_user: CurrentUser,
    two_factor_svc: TwoFactorServiceDep,
    audit_svc: AuditServiceDep,
) -> ApiResponse[TwoFactorDisableResponse]:
    await two_factor_svc.disable(
        user_id=current_user.id,
        code=body.code,
        is_2fa_enabled=current_user.is_2fa_enabled,
        totp_secret_encrypted=current_user.totp_secret_encrypted,
    )

    await audit_svc.log(
        action=AuditAction.TWO_FACTOR_DISABLED,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={},
    )

    return ApiResponse(data=TwoFactorDisableResponse())


@router.get(
    "/2fa/status",
    response_model=ApiResponse[TwoFactorStatusResponse],
    summary="2FA 상태 조회",
    description="현재 사용자의 2FA 활성 여부와 잔여 백업 코드 존재 여부를 반환합니다.",
)
async def two_fa_status(
    current_user: CurrentUser,
    two_factor_svc: TwoFactorServiceDep,
) -> ApiResponse[TwoFactorStatusResponse]:
    result = await two_factor_svc.get_status(
        user_id=current_user.id,
        is_2fa_enabled=current_user.is_2fa_enabled,
    )
    return ApiResponse(data=result)


@router.post(
    "/2fa/login-verify",
    response_model=ApiResponse[LoginResponse],
    summary="2FA 로그인 2단계 검증",
    description=(
        "임시 토큰 + TOTP 코드(6자리) 또는 백업 코드(10자리) 검증 후 최종 토큰을 발급합니다."
    ),
)
async def two_fa_login_verify(
    body: TwoFactorLoginVerifyRequest,
    request: Request,
    auth_svc: AuthServiceDep,
    two_factor_svc: TwoFactorServiceDep,
    session_svc: SessionServiceDep,
    audit_svc: AuditServiceDep,
) -> ApiResponse[LoginResponse]:
    # 임시 토큰 검증 (GETDEL — 1회 사용)
    token_hash = hashlib.sha256(body.temp_token.encode()).hexdigest()
    raw = await auth_svc.get_and_delete_2fa_login_pending(token_hash)

    if raw is None:
        raise AuthErrors.invalid_temp_token()

    pending = json.loads(raw)
    user_id = uuid.UUID(pending["user_id"])
    ip = pending.get("ip_address", "unknown")
    ua = pending.get("user_agent", "")

    # 사용자 조회
    user = await auth_svc.get_user_by_id(user_id)

    # TOTP / 백업 코드 검증
    is_backup = len(body.code) > 6
    verified = await two_factor_svc.verify_code(
        user_id=user_id,
        code=body.code,
        totp_secret_encrypted=user.totp_secret_encrypted,
    )

    if not verified:
        await audit_svc.log(
            action=AuditAction.TWO_FACTOR_LOGIN_FAILED,
            ip_address=ip,
            user_agent=ua,
            user_id=user_id,
            details={"reason": "invalid_code"},
        )
        raise AuthErrors.invalid_totp_code()

    # 세션 생성 + 토큰 발급
    client, is_new = await session_svc.create_or_update_session(
        user_id=user_id,
        device_fingerprint=pending.get("device_fingerprint"),
        device_name=pending.get("device_name"),
        device_type=pending.get("device_type", "web"),
        ip_address=ip,
        user_agent=ua,
    )

    tokens = await auth_svc.issue_tokens_with_store(user, str(client.id))

    # Audit Logging
    await audit_svc.log(
        action=AuditAction.TWO_FACTOR_LOGIN_SUCCESS,
        ip_address=ip,
        user_agent=ua,
        user_id=user_id,
        details={"device_name": pending.get("device_name")},
    )

    if is_backup:
        remaining = await two_factor_svc.count_remaining_backup_codes(user_id)
        await audit_svc.log(
            action=AuditAction.TWO_FACTOR_BACKUP_USED,
            ip_address=ip,
            user_agent=ua,
            user_id=user_id,
            details={"remaining_count": remaining},
        )

    if is_new:
        await audit_svc.log(
            action=AuditAction.NEW_DEVICE_LOGIN,
            ip_address=ip,
            user_agent=ua,
            user_id=user_id,
            details={"device_name": pending.get("device_name"), "device_fingerprint": pending.get("device_fingerprint")},
        )

    return ApiResponse(data=LoginResponse(user=UserResponse.from_user(user), tokens=tokens))


# ── 세션 관리 ──────────────────────────────────────────────────────────────────


@router.get(
    "/sessions",
    response_model=ApiResponse[SessionListResponse],
    summary="활성 세션 목록",
    description="현재 사용자의 모든 활성 디바이스 세션을 반환합니다.",
)
async def list_sessions(
    current_user: CurrentUser,
    current_client_id: CurrentClientId,
    session_svc: SessionServiceDep,
) -> ApiResponse[SessionListResponse]:
    clients = await session_svc.list_sessions(current_user.id)
    sessions = [SessionResponse.from_client(c, current_client_id) for c in clients]
    return ApiResponse(data=SessionListResponse(sessions=sessions))


@router.delete(
    "/sessions/{client_id}",
    response_model=ApiResponse[dict],
    summary="세션 강제 종료",
    description="특정 디바이스 세션을 강제 종료하고 해당 Refresh Token을 폐기합니다.",
)
async def revoke_session(
    client_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    session_svc: SessionServiceDep,
    audit_svc: AuditServiceDep,
) -> ApiResponse[dict]:
    await session_svc.revoke_session(user_id=current_user.id, client_id=client_id)

    await audit_svc.log(
        action=AuditAction.SESSION_REVOKED,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={"revoked_client_id": str(client_id)},
    )

    return ApiResponse(data={"message": "세션이 종료되었습니다."})


@router.post(
    "/logout-all",
    response_model=ApiResponse[LogoutAllResponse],
    summary="전체 로그아웃",
    description="현재 세션을 제외한 모든 디바이스 세션을 종료합니다.",
)
async def logout_all(
    request: Request,
    current_user: CurrentUser,
    current_client_id: CurrentClientId,
    session_svc: SessionServiceDep,
    audit_svc: AuditServiceDep,
) -> ApiResponse[LogoutAllResponse]:
    # JWT payload의 client_id로 현재 세션 제외
    count = await session_svc.revoke_all_sessions(
        user_id=current_user.id,
        except_client_id=current_client_id,
    )

    await audit_svc.log(
        action=AuditAction.LOGOUT_ALL,
        ip_address=_get_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        user_id=current_user.id,
        details={"revoked_count": count},
    )

    return ApiResponse(data=LogoutAllResponse(revoked_count=count))
