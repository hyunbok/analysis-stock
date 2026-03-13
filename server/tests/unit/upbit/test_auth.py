"""UpbitJwtAuth 단위 테스트 — JWT HS512 토큰 생성 검증."""
from __future__ import annotations

import hashlib
from urllib.parse import urlencode

import jwt
import pytest

from app.providers.upbit.auth import UpbitJwtAuth


@pytest.fixture
def auth() -> UpbitJwtAuth:
    return UpbitJwtAuth(api_key="test-access-key", api_secret="test-secret-key")


# ── TC1: 기본 토큰 생성 ────────────────────────────────────────────────────────


def test_generate_without_query(auth: UpbitJwtAuth) -> None:
    """query_params 없이 생성 시 access_key, nonce 포함, query_hash 미포함."""
    token = auth.generate()
    payload = jwt.decode(token, "test-secret-key", algorithms=["HS512"])
    assert payload["access_key"] == "test-access-key"
    assert "nonce" in payload
    assert "query_hash" not in payload
    assert "query_hash_alg" not in payload


def test_generate_with_query_params(auth: UpbitJwtAuth) -> None:
    """query_params 있을 때 query_hash, query_hash_alg='SHA512' 포함."""
    params = {"market": "KRW-BTC"}
    token = auth.generate(query_params=params)
    payload = jwt.decode(token, "test-secret-key", algorithms=["HS512"])
    assert "query_hash" in payload
    assert payload["query_hash_alg"] == "SHA512"

    # hash 정합성 검증
    expected_hash = hashlib.sha512(urlencode(params).encode()).hexdigest()
    assert payload["query_hash"] == expected_hash


def test_generate_for_body(auth: UpbitJwtAuth) -> None:
    """POST body dict → query_hash 변환."""
    body = {"market": "KRW-BTC", "side": "bid", "ord_type": "limit"}
    token = auth.generate_for_body(body)
    payload = jwt.decode(token, "test-secret-key", algorithms=["HS512"])
    assert "query_hash" in payload
    assert payload["query_hash_alg"] == "SHA512"

    expected_hash = hashlib.sha512(urlencode(body).encode()).hexdigest()
    assert payload["query_hash"] == expected_hash


def test_query_hash_sha512(auth: UpbitJwtAuth) -> None:
    """_build_query_hash가 SHA-512 hex digest를 올바르게 반환."""
    params = {"uuid": "test-order-uuid"}
    result = auth._build_query_hash(params)
    expected = hashlib.sha512(urlencode(params).encode()).hexdigest()
    assert result == expected
    assert len(result) == 128  # SHA-512 hex = 128자


def test_authorization_header_format(auth: UpbitJwtAuth) -> None:
    """authorization_header()가 'Bearer {token}' 형식 반환."""
    header = auth.authorization_header()
    assert "Authorization" in header
    assert header["Authorization"].startswith("Bearer ")
    # Bearer 이후 토큰이 있는지
    token = header["Authorization"][7:]
    assert len(token) > 0


def test_nonce_uniqueness(auth: UpbitJwtAuth) -> None:
    """연속 호출 시 nonce가 매번 다름."""
    token1 = auth.generate()
    token2 = auth.generate()
    payload1 = jwt.decode(token1, "test-secret-key", algorithms=["HS512"])
    payload2 = jwt.decode(token2, "test-secret-key", algorithms=["HS512"])
    assert payload1["nonce"] != payload2["nonce"]


def test_algorithm_hs512(auth: UpbitJwtAuth) -> None:
    """JWT 헤더의 alg가 HS512."""
    token = auth.generate()
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "HS512"
