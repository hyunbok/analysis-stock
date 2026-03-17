"""인증 흐름 E2E 테스트 — 회원가입 → 이메일 인증 → 로그인 → 토큰 갱신 → 로그아웃.

TC-AUTH-E2E-01: 회원가입 → 이메일 인증 → 로그인 → 토큰 갱신 → 로그아웃
TC-AUTH-E2E-02: 비활성 계정 로그인 시도 → 차단 확인
TC-AUTH-E2E-03: 비밀번호 변경 → 기존 Refresh Token 무효화 → 재로그인
TC-AUTH-E2E-04: Rate Limit 초과 → 429 응답
TC-AUTH-E2E-05: 이메일 미인증 계정 로그인 → 403 차단
TC-AUTH-E2E-06: 만료/잘못된 토큰 → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


# ── TC-AUTH-E2E-01: 전체 인증 흐름 ────────────────────────────────────────────


@pytest.mark.anyio
async def test_auth_full_flow_register_verify_login_refresh_logout(
    e2e_client: AsyncClient,
    e2e_redis,
):
    """회원가입 → 이메일 인증 → 로그인 → 토큰 갱신 → 로그아웃 전체 흐름."""
    email = "auth_flow_01@e2etest.com"
    password = "TestFlow1234!"

    # 1. 회원가입
    resp = await e2e_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "nickname": "흐름테스터"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["email"] == email

    # 2. 이메일 인증 코드 조회 (fakeredis 직접 접근)
    code = await e2e_redis.get(f"email_verify:{email}")
    assert code is not None, "이메일 인증 코드가 Redis에 없음"
    assert len(code) == 6
    assert code.isdigit()

    # 3. 이메일 인증
    verify_resp = await e2e_client.post(
        "/api/v1/auth/verify-email",
        json={"email": email, "code": code},
    )
    assert verify_resp.status_code == 200
    verify_body = verify_resp.json()
    assert "message" in verify_body["data"]

    # 4. 인증 코드 소진 확인 (재사용 불가)
    reuse_resp = await e2e_client.post(
        "/api/v1/auth/verify-email",
        json={"email": email, "code": code},
    )
    assert reuse_resp.status_code == 400  # 이미 인증 완료 or 코드 만료

    # 5. 로그인
    login_resp = await e2e_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()["data"]
    assert login_data["requires_2fa"] is False
    assert login_data["user"]["email"] == email
    assert login_data["user"]["email_verified"] is True
    assert "access_token" in login_data["tokens"]
    assert "refresh_token" in login_data["tokens"]

    access_token = login_data["tokens"]["access_token"]
    refresh_token = login_data["tokens"]["refresh_token"]

    # 6. /users/me 접근 가능 확인
    me_resp = await e2e_client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()["data"]
    assert me_data["user"]["email"] == email

    # 7. 토큰 갱신
    refresh_resp = await e2e_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()["data"]["tokens"]
    assert "access_token" in new_tokens
    new_access = new_tokens["access_token"]
    assert new_access != access_token  # 새 토큰이어야 함

    # 8. 기존 refresh_token 재사용 → 실패 (토큰 로테이션)
    reuse_refresh_resp = await e2e_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert reuse_refresh_resp.status_code == 401

    # 9. 새 access_token으로 /users/me 접근
    me_resp2 = await e2e_client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert me_resp2.status_code == 200

    # 10. 로그아웃
    logout_resp = await e2e_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert logout_resp.status_code == 200

    # 11. 로그아웃 후 기존 access_token으로 접근 → 서비스에 따라 계속 유효 (짧은 TTL)
    # access_token은 stateless JWT이므로 즉시 무효화되지 않음 (refresh만 무효화)
    # → refresh_token으로 토큰 갱신 시도 → 실패해야 함
    post_logout_refresh = await e2e_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_tokens["refresh_token"]},
    )
    assert post_logout_refresh.status_code == 401


# ── TC-AUTH-E2E-02: 이메일 미인증 계정 로그인 차단 ────────────────────────────


@pytest.mark.anyio
async def test_auth_login_blocked_without_email_verification(
    e2e_client: AsyncClient,
    e2e_redis,
):
    """이메일 미인증 상태에서 로그인 시도 → 403 차단."""
    email = "unverified_02@e2etest.com"
    password = "Unverified1234!"

    # 회원가입 (인증 안 함)
    register_resp = await e2e_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "nickname": "미인증유저"},
    )
    assert register_resp.status_code == 201

    # 인증 없이 로그인 시도
    login_resp = await e2e_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 403
    error = login_resp.json()["error"]
    assert error["code"] == "EMAIL_NOT_VERIFIED"


# ── TC-AUTH-E2E-03: 잘못된 인증 코드 → 400 ───────────────────────────────────


@pytest.mark.anyio
async def test_auth_verify_email_wrong_code(
    e2e_client: AsyncClient,
    e2e_redis,
):
    """잘못된 인증 코드 제출 → 400."""
    email = "wrongcode_03@e2etest.com"
    password = "WrongCode1234!"

    await e2e_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "nickname": "코드오류테스터"},
    )

    # 잘못된 코드 제출
    bad_code_resp = await e2e_client.post(
        "/api/v1/auth/verify-email",
        json={"email": email, "code": "000000"},
    )
    assert bad_code_resp.status_code == 400
    assert "error" in bad_code_resp.json()


# ── TC-AUTH-E2E-04: 만료/잘못된 Access Token → 401 ───────────────────────────


@pytest.mark.anyio
async def test_auth_protected_route_with_invalid_token(
    e2e_client: AsyncClient,
):
    """잘못된 JWT로 보호된 엔드포인트 접근 → 401."""
    resp = await e2e_client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer invalid.jwt.token"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.anyio
async def test_auth_protected_route_without_token(
    e2e_client: AsyncClient,
):
    """토큰 없이 보호된 엔드포인트 접근 → 401."""
    resp = await e2e_client.get("/api/v1/users/me")
    assert resp.status_code == 401


# ── TC-AUTH-E2E-05: 잘못된 비밀번호 로그인 → 401 ─────────────────────────────


@pytest.mark.anyio
async def test_auth_login_wrong_password(
    e2e_client: AsyncClient,
    e2e_redis,
):
    """잘못된 비밀번호로 로그인 → 401."""
    email = "wrongpw_05@e2etest.com"

    # 가입 + 인증
    await e2e_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Correct1234!", "nickname": "비밀번호오류"},
    )
    code = await e2e_redis.get(f"email_verify:{email}")
    await e2e_client.post(
        "/api/v1/auth/verify-email",
        json={"email": email, "code": code},
    )

    # 잘못된 비밀번호 로그인
    login_resp = await e2e_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPW9999!"},
    )
    assert login_resp.status_code == 401
    assert login_resp.json()["error"]["code"] in ("UNAUTHORIZED", "INVALID_CREDENTIALS")


# ── TC-AUTH-E2E-06: 비밀번호 강도 검증 ───────────────────────────────────────


@pytest.mark.anyio
async def test_auth_register_weak_password_rejected(
    e2e_client: AsyncClient,
):
    """약한 비밀번호(8자 미만) 회원가입 → 422."""
    resp = await e2e_client.post(
        "/api/v1/auth/register",
        json={"email": "weakpw@e2etest.com", "password": "short", "nickname": "약한비번"},
    )
    assert resp.status_code == 422


# ── TC-AUTH-E2E-07: 중복 이메일 회원가입 → 409 ───────────────────────────────


@pytest.mark.anyio
async def test_auth_register_duplicate_email(
    e2e_client: AsyncClient,
    test_user: dict,
):
    """이미 존재하는 이메일로 회원가입 → 409."""
    resp = await e2e_client.post(
        "/api/v1/auth/register",
        json={
            "email": test_user["email"],
            "password": "Test1234!",
            "nickname": "중복이메일",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] in ("EMAIL_ALREADY_EXISTS", "CONFLICT")


# ── TC-AUTH-E2E-08: 토큰 없는 갱신 시도 → 401 ────────────────────────────────


@pytest.mark.anyio
async def test_auth_refresh_with_invalid_token(
    e2e_client: AsyncClient,
):
    """잘못된 refresh_token으로 토큰 갱신 시도 → 401."""
    resp = await e2e_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid-refresh-token"},
    )
    assert resp.status_code == 401
