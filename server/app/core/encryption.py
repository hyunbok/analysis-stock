"""AES-256-GCM TOTP 암호화 유틸리티 + 백업 코드 생성."""
from __future__ import annotations

import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_totp_secret(plaintext: str, key: bytes) -> bytes:
    """AES-256-GCM 암호화.

    Args:
        plaintext: 암호화할 TOTP Base32 secret.
        key: 32바이트 AES 키 (bytes.fromhex(TOTP_ENCRYPTION_KEY)).

    Returns:
        nonce(12) + ciphertext + auth_tag(16) — 연결된 bytes.
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return nonce + ciphertext


def decrypt_totp_secret(encrypted: bytes, key: bytes) -> str:
    """AES-256-GCM 복호화.

    Args:
        encrypted: encrypt_totp_secret() 반환값 (nonce + ciphertext + tag).
        key: 32바이트 AES 키.

    Returns:
        복호화된 TOTP Base32 secret.

    Raises:
        cryptography.exceptions.InvalidTag: 무결성 검증 실패 (키 불일치 또는 변조).
    """
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode()


# 혼동 문자 제외 알파벳 (0↔O, 1↔I/L 혼동 방지)
_BACKUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_backup_codes(count: int = 10) -> list[str]:
    """암호학적으로 안전한 10자리 백업 코드 생성.

    Args:
        count: 생성할 코드 수 (기본 10개).

    Returns:
        평문 백업 코드 리스트. verify 성공 시 1회만 반환하고 이후 재조회 불가.
    """
    return [
        "".join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(10))
        for _ in range(count)
    ]


def hash_backup_code(code: str) -> str:
    """백업 코드를 SHA-256 해시로 변환.

    Args:
        code: 평문 백업 코드 (10자리 영숫자).

    Returns:
        SHA-256 hex digest (64자) — user_totp_backup_codes.code_hash에 저장.
    """
    return hashlib.sha256(code.encode()).hexdigest()
