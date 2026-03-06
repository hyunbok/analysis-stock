"""JWT/bcrypt/email code 단위 테스트."""
from __future__ import annotations

import pytest
from jose import JWTError

from app.core import security


def test_hash_and_verify_password():
    hashed = security.hash_password("Str0ng!Pw")
    assert hashed != "Str0ng!Pw"
    assert security.verify_password("Str0ng!Pw", hashed)
    assert not security.verify_password("WrongPass", hashed)


def test_access_token_roundtrip():
    token = security.create_access_token(user_id="abc-123", email="test@example.com")
    payload = security.decode_access_token(token)
    assert payload["sub"] == "abc-123"
    assert payload["email"] == "test@example.com"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip():
    token = security.create_refresh_token(user_id="abc-123", client_id="client-456")
    payload = security.decode_refresh_token(token)
    assert payload["sub"] == "abc-123"
    assert payload["client_id"] == "client-456"
    assert payload["type"] == "refresh"


def test_decode_access_token_rejects_refresh():
    refresh = security.create_refresh_token(user_id="u1", client_id="c1")
    with pytest.raises(JWTError):
        security.decode_access_token(refresh)


def test_decode_refresh_token_rejects_access():
    access = security.create_access_token(user_id="u1", email="a@b.com")
    with pytest.raises(JWTError):
        security.decode_refresh_token(access)


def test_hash_token_deterministic():
    token = "some.jwt.token"
    assert security.hash_token(token) == security.hash_token(token)
    assert security.hash_token(token) != security.hash_token("different.token")


def test_generate_email_code_format():
    for _ in range(20):
        code = security.generate_email_code()
        assert len(code) == 6
        assert code.isdigit()
