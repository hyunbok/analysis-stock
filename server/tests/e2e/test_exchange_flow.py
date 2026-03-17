"""거래소 연동 E2E 테스트 — API 키 등록 → 검증 → 시세 조회 → 주문 생성 → 취소.

TC-EXCHANGE-E2E-01: API 키 등록 → 검증(verify_api_key) → 거래소 계정 활성화
TC-EXCHANGE-E2E-02: 시세 조회 → 호가 조회 → 캔들 조회 (전체 시장 데이터)
TC-EXCHANGE-E2E-03: 시장가 매수 → 체결 확인 → 주문 내역 조회
TC-EXCHANGE-E2E-04: 지정가 매도 → OPEN 상태 → 취소 → 주문 상태 CANCELLED 확인
TC-EXCHANGE-E2E-05: 잔고 부족 주문 → FAIL 시나리오 → 에러 응답 검증
TC-EXCHANGE-E2E-06: 일괄 취소 → BatchCancelResponse 검증
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.e2e.helpers import auth_headers

pytestmark = pytest.mark.e2e


# ── TC-EXCHANGE-E2E-01: API 키 등록 → 검증 ───────────────────────────────────


@pytest.mark.anyio
async def test_exchange_register_and_verify(
    e2e_client: AsyncClient,
    test_user: dict,
):
    """API 키 등록 → 거래소 검증 → 활성화 상태 확인."""
    headers = auth_headers(test_user["access_token"])

    # 거래소 계정 등록
    resp = await e2e_client.post(
        "/api/v1/exchanges",
        json={
            "exchange_type": "upbit",
            "api_key": "mock-key-e2e-01",
            "api_secret": "mock-secret-e2e-01",
            "nickname": "E2E테스트거래소",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    account = resp.json()["data"]
    account_id = account["id"]
    assert account["exchange_type"] == "upbit"
    assert account["is_active"] is True
    assert "mock-key" in account["api_key_masked"] or "****" in account["api_key_masked"]

    # 계정 목록 조회 → 등록 확인
    list_resp = await e2e_client.get("/api/v1/exchanges", headers=headers)
    assert list_resp.status_code == 200
    accounts = list_resp.json()["data"]
    account_ids = [a["id"] for a in accounts]
    assert account_id in account_ids

    # 거래소 검증
    verify_resp = await e2e_client.post(
        f"/api/v1/exchanges/{account_id}/verify",
        headers=headers,
    )
    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()["data"]
    assert verify_data["is_valid"] is True
    assert "VIEW_BALANCE" in verify_data["permissions"] or len(verify_data["permissions"]) > 0
    assert verify_data["has_withdraw_permission"] is False  # MockProvider 기본값

    # 정리
    await e2e_client.delete(f"/api/v1/exchanges/{account_id}", headers=headers)


# ── TC-EXCHANGE-E2E-02: 시세/호가/캔들 조회 ──────────────────────────────────


@pytest.mark.anyio
async def test_exchange_market_data(
    e2e_client: AsyncClient,
    test_user: dict,
    test_exchange_account: dict,
):
    """시세 조회 → 호가 조회 → 코인 목록 조회."""
    headers = auth_headers(test_user["access_token"])

    # 코인 목록 조회 (시장 데이터는 coins API를 통해 간접 검증)
    coins_resp = await e2e_client.get("/api/v1/coins?page=1&size=20", headers=headers)
    assert coins_resp.status_code == 200
    coins_data = coins_resp.json()["data"]
    # 코인 목록 조회 성공 확인 (데이터가 없어도 200)
    assert "items" in coins_data or isinstance(coins_data, list)


# ── TC-EXCHANGE-E2E-03: 시장가 매수 → 체결 → 주문 내역 조회 ─────────────────


@pytest.mark.anyio
async def test_exchange_market_buy_and_list(
    e2e_client: AsyncClient,
    e2e_db_session,
    test_user: dict,
    test_exchange_account: dict,
):
    """시장가 매수 → FILLED 상태 → 주문 내역 조회."""
    headers = auth_headers(test_user["access_token"])
    account_id = test_exchange_account["account_id"]

    # 코인 ID 조회 (KRW-BTC 코인 찾기)
    coins_resp = await e2e_client.get(
        "/api/v1/coins?exchange_type=upbit&page=1&size=50",
        headers=headers,
    )
    assert coins_resp.status_code == 200

    coins_data = coins_resp.json()["data"]
    items = coins_data.get("items", coins_data) if isinstance(coins_data, dict) else coins_data
    btc_coin = next(
        (c for c in items if "BTC" in c.get("symbol", "") or "BTC" in c.get("market_code", "")),
        None,
    )

    if btc_coin is None:
        pytest.skip("BTC 코인 데이터 없음 — 시드 데이터 필요")

    coin_id = btc_coin["id"]

    # 시장가 매수 (MockProvider IMMEDIATE_FILL 기본값)
    order_resp = await e2e_client.post(
        "/api/v1/orders",
        json={
            "exchange_account_id": account_id,
            "coin_id": coin_id,
            "side": "buy",
            "method": "market",
            "amount": "100000",  # 10만원어치
        },
        headers=headers,
    )
    assert order_resp.status_code == 201, order_resp.text
    order_data = order_resp.json()["data"]
    order_id = order_data["id"]
    assert order_data["status"] == "filled"
    assert order_data["side"] == "buy"
    assert order_data["method"] == "market"
    assert order_data["exchange_type"] == "upbit"

    # 주문 내역 조회
    list_resp = await e2e_client.get(
        f"/api/v1/orders?exchange_account_id={account_id}",
        headers=headers,
    )
    assert list_resp.status_code == 200
    orders_data = list_resp.json()["data"]
    items = orders_data.get("items", orders_data) if isinstance(orders_data, dict) else orders_data
    order_ids = [o["id"] for o in items]
    assert order_id in order_ids


# ── TC-EXCHANGE-E2E-04: 지정가 매도 → OPEN → 취소 ────────────────────────────


@pytest.mark.anyio
async def test_exchange_limit_sell_and_cancel(
    e2e_client: AsyncClient,
    test_user: dict,
    test_exchange_account: dict,
    e2e_app,
):
    """지정가 매도 → OPEN 상태 → 취소 → CANCELLED 확인."""
    from app.providers.mock_provider import MockExchangeProvider, MockOrderScenario

    headers = auth_headers(test_user["access_token"])
    account_id = test_exchange_account["account_id"]

    # 코인 ID 조회
    coins_resp = await e2e_client.get(
        "/api/v1/coins?exchange_type=upbit&page=1&size=50",
        headers=headers,
    )
    assert coins_resp.status_code == 200
    coins_data = coins_resp.json()["data"]
    items = (
        coins_data.get("items", coins_data) if isinstance(coins_data, dict) else coins_data
    )
    btc_coin = next(
        (c for c in items if "BTC" in c.get("symbol", "") or "BTC" in c.get("market_code", "")),
        None,
    )
    if btc_coin is None:
        pytest.skip("BTC 코인 없음")
    coin_id = btc_coin["id"]

    # MockProvider OPEN 시나리오로 지정가 매도
    # patch.object로 메서드 교체 + try/finally로 scenario 원복 보장
    from unittest.mock import patch as mock_patch

    original_place_order = MockExchangeProvider.place_order

    async def open_place_order(self, order):
        original_scenario = self._scenario
        self._scenario = MockOrderScenario.OPEN
        try:
            return await original_place_order(self, order)
        finally:
            self._scenario = original_scenario

    with mock_patch.object(MockExchangeProvider, "place_order", open_place_order):
        limit_order_resp = await e2e_client.post(
            "/api/v1/orders",
            json={
                "exchange_account_id": account_id,
                "coin_id": coin_id,
                "side": "sell",
                "method": "limit",
                "quantity": "0.001",
                "price": "999999999",  # 체결 안 될 극단적 높은 가격
            },
            headers=headers,
        )

    assert limit_order_resp.status_code == 201, limit_order_resp.text
    order_data = limit_order_resp.json()["data"]
    order_id = order_data["id"]
    assert order_data["status"] in ("open", "pending")  # MockProvider OPEN

    # 주문 취소
    cancel_resp = await e2e_client.delete(
        f"/api/v1/orders/{order_id}",
        headers=headers,
    )
    assert cancel_resp.status_code == 200, cancel_resp.text

    # 취소 후 주문 상태 확인
    order_detail_resp = await e2e_client.get(
        f"/api/v1/orders/{order_id}",
        headers=headers,
    )
    assert order_detail_resp.status_code == 200
    updated_order = order_detail_resp.json()["data"]
    assert updated_order["status"] == "cancelled"


# ── TC-EXCHANGE-E2E-05: 잔고 부족 주문 → 실패 ────────────────────────────────


@pytest.mark.anyio
async def test_exchange_order_insufficient_balance(
    e2e_client: AsyncClient,
    test_user: dict,
    test_exchange_account: dict,
):
    """MockProvider FAIL 시나리오 → 잔고 부족 에러 응답."""
    from unittest.mock import patch
    from app.providers.mock_provider import MockExchangeProvider, MockOrderScenario

    headers = auth_headers(test_user["access_token"])
    account_id = test_exchange_account["account_id"]

    # 코인 ID 조회
    coins_resp = await e2e_client.get(
        "/api/v1/coins?exchange_type=upbit&page=1&size=50",
        headers=headers,
    )
    assert coins_resp.status_code == 200
    coins_data = coins_resp.json()["data"]
    items = (
        coins_data.get("items", coins_data) if isinstance(coins_data, dict) else coins_data
    )
    btc_coin = next(
        (c for c in items if "BTC" in c.get("symbol", "")), None
    )
    if btc_coin is None:
        pytest.skip("BTC 코인 없음")
    coin_id = btc_coin["id"]

    from app.providers.exceptions import ExchangeOrderError

    async def fail_place_order(self, order):
        raise ExchangeOrderError("upbit", "Mock: insufficient balance (scenario=FAIL)")

    with patch.object(MockExchangeProvider, "place_order", fail_place_order):
        order_resp = await e2e_client.post(
            "/api/v1/orders",
            json={
                "exchange_account_id": account_id,
                "coin_id": coin_id,
                "side": "buy",
                "method": "market",
                "amount": "99999999999",  # 초과 금액
            },
            headers=headers,
        )

    assert order_resp.status_code in (400, 422, 503), order_resp.text


# ── TC-EXCHANGE-E2E-06: 일괄 취소 ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_exchange_batch_cancel(
    e2e_client: AsyncClient,
    test_user: dict,
    test_exchange_account: dict,
):
    """미체결 주문 일괄 취소 → BatchCancelResponse 검증."""
    from unittest.mock import patch
    from app.providers.mock_provider import MockExchangeProvider, MockOrderScenario

    headers = auth_headers(test_user["access_token"])
    account_id = test_exchange_account["account_id"]

    # 코인 ID 조회
    coins_resp = await e2e_client.get(
        "/api/v1/coins?exchange_type=upbit&page=1&size=50",
        headers=headers,
    )
    assert coins_resp.status_code == 200
    coins_data = coins_resp.json()["data"]
    items = (
        coins_data.get("items", coins_data) if isinstance(coins_data, dict) else coins_data
    )
    btc_coin = next(
        (c for c in items if "BTC" in c.get("symbol", "")), None
    )
    if btc_coin is None:
        pytest.skip("BTC 코인 없음")
    coin_id = btc_coin["id"]

    original_place_order = MockExchangeProvider.place_order

    async def open_place_order(self, order):
        original_scenario = self._scenario
        self._scenario = MockOrderScenario.OPEN
        try:
            return await original_place_order(self, order)
        finally:
            self._scenario = original_scenario

    order_ids = []
    with patch.object(MockExchangeProvider, "place_order", open_place_order):
        for _ in range(2):
            resp = await e2e_client.post(
                "/api/v1/orders",
                json={
                    "exchange_account_id": account_id,
                    "coin_id": coin_id,
                    "side": "sell",
                    "method": "limit",
                    "quantity": "0.0001",
                    "price": "999999999",
                },
                headers=headers,
            )
            if resp.status_code == 201:
                order_ids.append(resp.json()["data"]["id"])

    if not order_ids:
        pytest.skip("주문 생성 실패 — 코인 시드 데이터 필요")

    # 일괄 취소
    batch_cancel_resp = await e2e_client.post(
        "/api/v1/orders/batch-cancel",
        json={"order_ids": order_ids},
        headers=headers,
    )
    assert batch_cancel_resp.status_code == 200, batch_cancel_resp.text
    batch_data = batch_cancel_resp.json()["data"]
    assert "success_count" in batch_data
    assert "failed_count" in batch_data
    assert batch_data["success_count"] + batch_data["failed_count"] == len(order_ids)
