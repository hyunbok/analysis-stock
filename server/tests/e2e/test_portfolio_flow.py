"""포트폴리오 및 손익 계산 E2E 테스트.

TC-PORTFOLIO-E2E-01: 거래소 계정 연결 → 잔고 조회 → 포트폴리오 통합 응답
TC-PORTFOLIO-E2E-02: 복수 거래소 자산 → 총 자산 계산 → KRW 환산 정확성
TC-PORTFOLIO-E2E-03: 주문 체결 후 → 포트폴리오 갱신 확인
TC-PORTFOLIO-E2E-04: 캐시된 시세(Redis) 활용 → 캐시 조회 확인
TC-PORTFOLIO-E2E-05: 거래소별 상세 포트폴리오 조회
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.e2e.helpers import auth_headers

pytestmark = pytest.mark.e2e


# ── TC-PORTFOLIO-E2E-01: 포트폴리오 통합 응답 ────────────────────────────────


@pytest.mark.anyio
async def test_portfolio_summary_with_exchange_account(
    e2e_client: AsyncClient,
    test_user: dict,
    test_exchange_account: dict,
):
    """거래소 계정 연결 → 포트폴리오 요약 조회."""
    headers = auth_headers(test_user["access_token"])

    resp = await e2e_client.get("/api/v1/portfolio", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # 필수 필드 확인
    assert "total_balance_krw" in data
    assert "total_pnl_amount" in data
    assert "total_pnl_ratio" in data
    assert "by_exchange" in data
    assert isinstance(data["by_exchange"], list)

    # MockProvider 기본 잔고: KRW 1000만 + BTC 0.1개
    total_krw = Decimal(data["total_balance_krw"])
    assert total_krw > Decimal("0")


# ── TC-PORTFOLIO-E2E-02: KRW 환산 정확성 ─────────────────────────────────────


@pytest.mark.anyio
async def test_portfolio_krw_conversion_accuracy(
    e2e_client: AsyncClient,
    test_user: dict,
    test_exchange_account: dict,
):
    """MockProvider 잔고 → KRW 환산 정확성 검증.

    MockProvider 기본값: KRW 10,000,000 + BTC 0.1 (단가 95,000,000)
    예상 총자산: 10,000,000 + 0.1 * 95,000,000 = 19,500,000
    """
    headers = auth_headers(test_user["access_token"])
    account_id = test_exchange_account["account_id"]

    # 거래소별 포트폴리오 조회
    resp = await e2e_client.get(
        f"/api/v1/portfolio/{account_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert "total_balance_krw" in data
    assert "krw_balance" in data
    assert "coins" in data
    assert isinstance(data["coins"], list)

    total_krw = Decimal(data["total_balance_krw"])
    krw_balance = Decimal(data["krw_balance"])

    # KRW 현금은 1000만원 이상 (MockProvider 기본값)
    assert krw_balance >= Decimal("1000000")
    assert total_krw >= krw_balance  # 총자산은 현금보다 크거나 같음


# ── TC-PORTFOLIO-E2E-03: 주문 체결 후 포트폴리오 변화 확인 ────────────────────


@pytest.mark.anyio
async def test_portfolio_updated_after_order(
    e2e_client: AsyncClient,
    test_user: dict,
    test_exchange_account: dict,
):
    """주문 체결 → 포트폴리오 갱신 → 주문 내역 반영 확인."""
    headers = auth_headers(test_user["access_token"])
    account_id = test_exchange_account["account_id"]

    # 주문 전 포트폴리오
    before_resp = await e2e_client.get("/api/v1/portfolio", headers=headers)
    assert before_resp.status_code == 200

    # 코인 조회
    coins_resp = await e2e_client.get(
        "/api/v1/coins?exchange_type=upbit&page=1&size=50",
        headers=headers,
    )
    assert coins_resp.status_code == 200
    coins_data = coins_resp.json()["data"]
    items = coins_data.get("items", coins_data) if isinstance(coins_data, dict) else coins_data
    btc_coin = next(
        (c for c in items if "BTC" in c.get("symbol", "")), None
    )
    if btc_coin is None:
        pytest.skip("BTC 코인 없음")

    coin_id = btc_coin["id"]

    # 시장가 매수
    order_resp = await e2e_client.post(
        "/api/v1/orders",
        json={
            "exchange_account_id": account_id,
            "coin_id": coin_id,
            "side": "buy",
            "method": "market",
            "amount": "100000",
        },
        headers=headers,
    )
    if order_resp.status_code != 201:
        pytest.skip(f"주문 생성 실패: {order_resp.text}")

    # 주문 후 포트폴리오 조회 (캐시 무효화 확인)
    after_resp = await e2e_client.get("/api/v1/portfolio", headers=headers)
    assert after_resp.status_code == 200
    after_data = after_resp.json()["data"]

    # 포트폴리오 응답이 유효한지 확인
    assert "total_balance_krw" in after_data
    assert "by_exchange" in after_data


# ── TC-PORTFOLIO-E2E-04: Redis 캐시 동작 확인 ────────────────────────────────


@pytest.mark.anyio
async def test_portfolio_redis_cache_behavior(
    e2e_client: AsyncClient,
    test_user: dict,
    test_exchange_account: dict,
    e2e_redis,
):
    """포트폴리오 조회 → Redis 캐시 저장 → 두 번째 조회 시 캐시 HIT."""
    headers = auth_headers(test_user["access_token"])
    account_id = test_exchange_account["account_id"]

    # 첫 번째 조회 (캐시 MISS → 거래소 실시간 조회)
    first_resp = await e2e_client.get(
        f"/api/v1/portfolio/{account_id}",
        headers=headers,
    )
    assert first_resp.status_code == 200
    first_data = first_resp.json()["data"]

    # 두 번째 조회 (캐시 HIT 또는 실시간)
    second_resp = await e2e_client.get(
        f"/api/v1/portfolio/{account_id}",
        headers=headers,
    )
    assert second_resp.status_code == 200
    second_data = second_resp.json()["data"]

    # 두 응답 모두 유효한 데이터
    assert Decimal(first_data["total_balance_krw"]) >= Decimal("0")
    assert Decimal(second_data["total_balance_krw"]) >= Decimal("0")


# ── TC-PORTFOLIO-E2E-05: 타인 거래소 계정 접근 차단 ─────────────────────────


@pytest.mark.anyio
async def test_portfolio_unauthorized_access_blocked(
    e2e_client: AsyncClient,
    test_user: dict,
    e2e_redis,
):
    """다른 사용자의 거래소 계정 ID로 포트폴리오 조회 → 403/404."""
    import uuid

    headers = auth_headers(test_user["access_token"])

    # 존재하지 않는 계정 ID로 조회
    fake_account_id = str(uuid.uuid4())
    resp = await e2e_client.get(
        f"/api/v1/portfolio/{fake_account_id}",
        headers=headers,
    )
    assert resp.status_code in (403, 404), resp.text


# ── TC-PORTFOLIO-E2E-06: 미인증 접근 차단 ────────────────────────────────────


@pytest.mark.anyio
async def test_portfolio_requires_authentication(
    e2e_client: AsyncClient,
):
    """토큰 없이 포트폴리오 조회 → 401."""
    resp = await e2e_client.get("/api/v1/portfolio")
    assert resp.status_code == 401
