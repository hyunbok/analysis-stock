"""CoinOneHmacAuth 단위 테스트 — HMAC-SHA512 서명 검증 (7건)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid

import pytest

from app.providers.coinone.auth import CoinOneHmacAuth


@pytest.fixture
def auth() -> CoinOneHmacAuth:
    return CoinOneHmacAuth(api_key="test-access-key", api_secret="test-secret-key")


# ── TC1: payload base64 정합성 ─────────────────────────────────────────────────


def test_sign_payload_base64(auth: CoinOneHmacAuth) -> None:
    """body → JSON → base64 인코딩 정합성 검증."""
    body = {"side": "BUY", "target_currency": "BTC"}
    signed_body, headers = auth.sign(body)

    # 헤더에서 payload_b64 추출
    payload_b64 = headers["X-COINONE-PAYLOAD"]

    # payload_b64 디코딩 → JSON 파싱
    decoded = json.loads(base64.b64decode(payload_b64.encode()).decode())

    # signed_body의 내용이 payload에 포함되어 있어야 함
    assert decoded["access_token"] == "test-access-key"
    assert decoded["side"] == "BUY"
    assert decoded["target_currency"] == "BTC"


# ── TC2: HMAC-SHA512 서명 검증 ─────────────────────────────────────────────────


def test_sign_hmac_sha512(auth: CoinOneHmacAuth) -> None:
    """HMAC-SHA512 서명 검증 — 알려진 입력 → 기대 출력."""
    signed_body, headers = auth.sign({})

    payload_b64 = headers["X-COINONE-PAYLOAD"]
    signature = headers["X-COINONE-SIGNATURE"]

    # 직접 HMAC-SHA512 계산
    expected_signature = hmac.new(
        b"test-secret-key",
        payload_b64.encode(),
        hashlib.sha512,
    ).hexdigest()

    assert signature == expected_signature


# ── TC3: access_token 자동 삽입 ────────────────────────────────────────────────


def test_sign_includes_access_token(auth: CoinOneHmacAuth) -> None:
    """body에 access_token 자동 삽입 확인."""
    body = {"qty": "0.001"}
    signed_body, headers = auth.sign(body)

    assert "access_token" in signed_body
    assert signed_body["access_token"] == "test-access-key"
    # 원본 body는 변경되지 않아야 함
    assert "access_token" not in body


# ── TC4: UUID v4 nonce 포함 ────────────────────────────────────────────────────


def test_sign_includes_uuid_nonce(auth: CoinOneHmacAuth) -> None:
    """nonce가 UUID v4 형식으로 포함되는지 확인."""
    signed_body, _ = auth.sign({})

    assert "nonce" in signed_body
    # UUID 형식 검증
    try:
        parsed = uuid.UUID(signed_body["nonce"])
        assert parsed.version == 4
    except ValueError:
        pytest.fail(f"nonce is not a valid UUID v4: {signed_body['nonce']}")


# ── TC5: nonce 고유성 ──────────────────────────────────────────────────────────


def test_nonce_uniqueness(auth: CoinOneHmacAuth) -> None:
    """연속 호출 시 nonce가 매번 다름."""
    _, _ = auth.sign({})
    body1, _ = auth.sign({})
    body2, _ = auth.sign({})

    assert body1["nonce"] != body2["nonce"]


# ── TC6: 헤더 형식 확인 ────────────────────────────────────────────────────────


def test_signed_headers_format(auth: CoinOneHmacAuth) -> None:
    """X-COINONE-PAYLOAD, X-COINONE-SIGNATURE 헤더 존재 확인."""
    _, headers = auth.sign({})

    assert "X-COINONE-PAYLOAD" in headers
    assert "X-COINONE-SIGNATURE" in headers
    # PAYLOAD는 유효한 base64
    assert len(headers["X-COINONE-PAYLOAD"]) > 0
    # SIGNATURE는 SHA-512 hex = 128자
    assert len(headers["X-COINONE-SIGNATURE"]) == 128


# ── TC7: None body 처리 ────────────────────────────────────────────────────────


def test_sign_none_body(auth: CoinOneHmacAuth) -> None:
    """body=None 시 access_token + nonce만 포함된 body 생성."""
    signed_body, headers = auth.sign(None)

    assert "access_token" in signed_body
    assert "nonce" in signed_body
    # access_token과 nonce 외의 추가 키 없음
    assert set(signed_body.keys()) == {"access_token", "nonce"}
    assert "X-COINONE-PAYLOAD" in headers
    assert "X-COINONE-SIGNATURE" in headers
