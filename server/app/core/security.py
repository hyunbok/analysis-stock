"""JWT 토큰 생성/검증, bcrypt 해싱, 인증 코드 생성 유틸리티."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


# ── 비밀번호 ──────────────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """bcrypt(cost=12) 해싱.

    Args:
        plain: 평문 비밀번호.

    Returns:
        bcrypt 해시 문자열.
    """
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """bcrypt 검증.

    Args:
        plain: 평문 비밀번호.
        hashed: bcrypt 해시.

    Returns:
        일치 여부.
    """
    return _pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────────────────


def create_access_token(user_id: str, email: str, client_id: str | None = None) -> str:
    """Access JWT 생성 (30분 만료).

    Args:
        user_id: 사용자 UUID 문자열.
        email: 사용자 이메일.
        client_id: 디바이스 세션 UUID 문자열 (현재 세션 식별용, 선택).

    Returns:
        서명된 JWT 문자열.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict = {
        "sub": user_id,
        "type": "access",
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if client_id is not None:
        payload["client_id"] = client_id
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str, client_id: str) -> str:
    """Refresh JWT 생성 (14일 만료).

    Args:
        user_id: 사용자 UUID 문자열.
        client_id: 기기 세션 식별자 UUID 문자열.

    Returns:
        서명된 JWT 문자열.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "client_id": client_id,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Access JWT 검증 및 페이로드 반환.

    Args:
        token: JWT 문자열.

    Returns:
        디코딩된 페이로드 dict.

    Raises:
        JWTError: 만료, 변조, 타입 불일치 시.
    """
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != "access":
        raise JWTError("Token type mismatch: expected access")
    return payload


def decode_refresh_token(token: str) -> dict:
    """Refresh JWT 검증 및 페이로드 반환.

    Args:
        token: JWT 문자열.

    Returns:
        디코딩된 페이로드 dict.

    Raises:
        JWTError: 만료, 변조, 타입 불일치 시.
    """
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != "refresh":
        raise JWTError("Token type mismatch: expected refresh")
    return payload


# ── 토큰 해시 ────────────────────────────────────────────────────────────────


def hash_token(token: str) -> str:
    """SHA-256 해시 생성 (Redis 저장용). 원본 토큰은 저장하지 않는다.

    Args:
        token: 원본 JWT 문자열.

    Returns:
        hex digest 문자열.
    """
    return hashlib.sha256(token.encode()).hexdigest()


# ── 이메일 인증 코드 ──────────────────────────────────────────────────────────


def generate_email_code() -> str:
    """6자리 숫자 인증 코드 생성 (secrets.randbelow 암호학적 안전 난수).

    Returns:
        6자리 zero-padded 숫자 문자열.
    """
    return str(secrets.randbelow(10**6)).zfill(6)
