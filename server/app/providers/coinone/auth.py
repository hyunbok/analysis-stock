"""CoinOne HMAC-SHA512 인증 헤더 생성 유틸리티."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Any


class CoinOneHmacAuth:
    """CoinOne HMAC-SHA512 인증 헤더 생성기.

    CoinOne 인증 방식:
    - 공개 API (시세/호가/캔들): 인증 불필요 (GET)
    - 비공개 API (주문/잔고): POST + HMAC 헤더 필수
    - 서명 절차:
      1. 요청 body dict에 access_token, nonce(UUID4) 삽입
      2. JSON 직렬화 → Base64 인코딩 → X-COINONE-PAYLOAD 헤더
      3. HMAC-SHA512(payload_base64, secret_key) → hex digest → X-COINONE-SIGNATURE 헤더
    """

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key         # CoinOne access_token
        self._api_secret = api_secret.encode()  # hmac은 bytes 필요

    def sign(
        self, body: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """body에 인증 필드 추가 → (signed_body, auth_headers) 반환.

        단일 메서드로 body와 headers를 함께 반환하는 이유:
        CoinOne은 POST body == payload 원본이므로 body도 함께 돌려줘야
        _request()에서 json=signed_body로 전달 가능.

        Args:
            body: 요청 파라미터 dict (access_token, nonce 제외).
                  None 시 access_token + nonce만 포함된 body 생성.

        Returns:
            (signed_body, headers) 튜플:
            - signed_body: access_token + nonce 포함된 최종 body (원본 dict 변경 없음)
            - headers: X-COINONE-PAYLOAD + X-COINONE-SIGNATURE
        """
        # ⚠️ 원본 dict mutation 방지: spread 연산자로 복사
        signed_body: dict[str, Any] = {
            "access_token": self._api_key,
            "nonce": str(uuid.uuid4()),
            **(body or {}),
        }
        payload_bytes = json.dumps(signed_body).encode()
        payload_b64 = base64.b64encode(payload_bytes).decode()
        signature = hmac.new(
            self._api_secret,
            payload_b64.encode(),
            hashlib.sha512,
        ).hexdigest()
        headers = {
            "X-COINONE-PAYLOAD": payload_b64,
            "X-COINONE-SIGNATURE": signature,
        }
        return signed_body, headers
