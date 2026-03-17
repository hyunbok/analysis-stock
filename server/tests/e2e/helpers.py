"""E2E 테스트 공용 헬퍼 — 반복 흐름 추상화."""
from __future__ import annotations

from httpx import AsyncClient


async def register_and_login(
    client: AsyncClient,
    redis,
    email: str = "helper@test.com",
    password: str = "Test1234!",
    nickname: str = "헬퍼유저",
) -> dict:
    """회원가입 → 이메일 인증 → 로그인 전체 흐름.

    Returns:
        {"user_id": str, "access_token": str, "refresh_token": str, "email": str}
    """
    # 1. 회원가입
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "nickname": nickname},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"

    # 2. 이메일 인증
    code = await redis.get(f"email_verify:{email}")
    assert code is not None, f"인증 코드 Redis 미존재: email_verify:{email}"
    verify_resp = await client.post(
        "/api/v1/auth/verify-email",
        json={"email": email, "code": code},
    )
    assert verify_resp.status_code == 200, f"verify-email failed: {verify_resp.text}"

    # 3. 로그인
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200, f"login failed: {login_resp.text}"
    data = login_resp.json()["data"]

    return {
        "user_id": data["user"]["id"],
        "access_token": data["tokens"]["access_token"],
        "refresh_token": data["tokens"]["refresh_token"],
        "email": email,
    }


def auth_headers(access_token: str) -> dict[str, str]:
    """Authorization 헤더 딕셔너리 반환."""
    return {"Authorization": f"Bearer {access_token}"}
