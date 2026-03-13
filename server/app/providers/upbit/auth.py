"""Upbit JWT HS512 인증 토큰 생성 유틸리티."""
from __future__ import annotations

import hashlib
import uuid
from urllib.parse import urlencode

import jwt


class UpbitJwtAuth:
    """Upbit HMAC-SHA512 JWT 토큰 생성기.

    Upbit 인증 방식:
    - 공개 API (시세/호가/캔들): 인증 불필요
    - 비공개 API (주문/잔고): Authorization: Bearer {JWT}
    - JWT Header: {"alg": "HS512", "typ": "JWT"}
    - JWT Payload: {access_key, nonce (UUID4)}
    - query params 있는 경우: payload에 query_hash (SHA-512 hex), query_hash_alg: "SHA512" 추가
    - POST body 있는 경우: body를 "key=value&key=value" 형식으로 변환 후 SHA-512 해시
    - Secret Key는 Base64 인코딩되어 있지 않으므로 그대로 사용
    """

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret

    def generate(self, query_params: dict[str, str] | None = None) -> str:
        """Bearer 토큰 문자열 생성 (prefix 없음, 헤더에서 f"Bearer {token}" 사용).

        Args:
            query_params: DELETE /v1/order 등 query string 있는 요청 시 전달.
                          내부에서 SHA-512 query_hash로 변환.

        Returns:
            JWT 토큰 문자열.
        """
        payload: dict[str, str] = {
            "access_key": self._api_key,
            "nonce": str(uuid.uuid4()),
        }
        if query_params:
            payload["query_hash"] = self._build_query_hash(query_params)
            payload["query_hash_alg"] = "SHA512"
        return jwt.encode(payload, self._api_secret, algorithm="HS512")

    def generate_for_body(self, json_body: dict[str, str]) -> str:
        """POST body가 있는 요청용 JWT 생성.

        body를 "key=value&key=value" 형식으로 변환 후 query_hash 생성.

        Args:
            json_body: POST 요청 body dict.

        Returns:
            JWT 토큰 문자열.
        """
        body_string = urlencode(json_body)
        query_hash = hashlib.sha512(body_string.encode()).hexdigest()
        payload: dict[str, str] = {
            "access_key": self._api_key,
            "nonce": str(uuid.uuid4()),
            "query_hash": query_hash,
            "query_hash_alg": "SHA512",
        }
        return jwt.encode(payload, self._api_secret, algorithm="HS512")

    def authorization_header(
        self, query_params: dict[str, str] | None = None
    ) -> dict[str, str]:
        """{"Authorization": "Bearer {token}"} 딕셔너리 반환.

        Args:
            query_params: query string이 있는 요청 시 전달 (GET/DELETE with params).

        Returns:
            Authorization 헤더 딕셔너리.
        """
        token = self.generate(query_params)
        return {"Authorization": f"Bearer {token}"}

    def _build_query_hash(self, params: dict[str, str]) -> str:
        """query string을 SHA-512 hex digest로 변환.

        Args:
            params: query string 파라미터 딕셔너리.

        Returns:
            SHA-512 hex digest 문자열.
        """
        query_string = urlencode(params)
        return hashlib.sha512(query_string.encode()).hexdigest()
