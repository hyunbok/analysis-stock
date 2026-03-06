"""인증 관련 Redis 캐시 서비스 — Refresh Token, 세션 관리, 이메일 인증."""
from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.core.redis_keys import RedisKey, RedisTTL

logger = logging.getLogger(__name__)


class AuthCacheService:
    """JWT Refresh Token 및 인증 관련 캐시 관리"""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def store_refresh_token(
        self, user_id: str, client_id: str, token_hash: str
    ) -> None:
        """Refresh token 해시 저장 + 세션 인덱스 등록"""
        pipe = self._redis.pipeline()
        pipe.set(
            RedisKey.refresh_token(user_id, client_id),
            token_hash,
            ex=RedisTTL.REFRESH_TOKEN,
        )
        pipe.sadd(RedisKey.refresh_index(user_id), client_id)
        pipe.expire(RedisKey.refresh_index(user_id), RedisTTL.REFRESH_TOKEN)
        await pipe.execute()

    async def get_refresh_token(self, user_id: str, client_id: str) -> str | None:
        """저장된 refresh token 해시 조회"""
        return await self._redis.get(RedisKey.refresh_token(user_id, client_id))

    async def revoke_refresh_token(self, user_id: str, client_id: str) -> None:
        """특정 세션의 refresh token 폐기"""
        pipe = self._redis.pipeline()
        pipe.delete(RedisKey.refresh_token(user_id, client_id))
        pipe.srem(RedisKey.refresh_index(user_id), client_id)
        await pipe.execute()

    async def revoke_all_sessions(self, user_id: str) -> int:
        """사용자의 모든 세션 폐기. 폐기한 세션 수 반환."""
        client_ids: list[str] = await self.list_sessions(user_id)
        if not client_ids:
            return 0

        pipe = self._redis.pipeline()
        for client_id in client_ids:
            pipe.delete(RedisKey.refresh_token(user_id, client_id))
        pipe.delete(RedisKey.refresh_index(user_id))
        await pipe.execute()
        return len(client_ids)

    async def list_sessions(self, user_id: str) -> list[str]:
        """사용자의 모든 활성 client_id 목록 반환"""
        members = await self._redis.smembers(RedisKey.refresh_index(user_id))
        return list(members)

    async def store_email_verify_code(self, email: str, code: str) -> None:
        """이메일 인증 코드 저장 (10분 TTL)"""
        await self._redis.set(
            RedisKey.email_verify(email),
            code,
            ex=RedisTTL.EMAIL_VERIFY,
        )

    async def verify_email_code(self, email: str, code: str) -> bool:
        """인증 코드 검증 후 삭제 (1회용). 일치 여부 반환.

        GETDEL로 원자적 조회+삭제 — TOCTOU 레이스 컨디션 방지 (Redis 6.2+).
        """
        stored = await self._redis.getdel(RedisKey.email_verify(email))
        return stored is not None and stored == code

    async def store_password_reset_token(self, token: str, user_id: str) -> None:
        """비밀번호 재설정 토큰 저장 (1시간 TTL)"""
        await self._redis.set(
            RedisKey.password_reset(token),
            user_id,
            ex=RedisTTL.PASSWORD_RESET,
        )

    async def get_password_reset_user(self, token: str) -> str | None:
        """재설정 토큰으로 user_id 조회"""
        return await self._redis.get(RedisKey.password_reset(token))

    async def revoke_password_reset_token(self, token: str) -> None:
        """재설정 토큰 폐기"""
        await self._redis.delete(RedisKey.password_reset(token))

    async def get_login_attempts(self, email: str) -> int:
        """이메일 기반 로그인 시도 횟수 조회."""
        val = await self._redis.get(RedisKey.rate_login_email(email))
        return int(val) if val else 0

    async def increment_login_attempts(self, email: str, window: int) -> int:
        """로그인 시도 횟수 증가 후 반환. 고정 윈도우 TTL 적용.

        nx=True: 첫 번째 incr 시에만 TTL 설정 (이후 실패에서 리셋 방지).
        설계서 §10.3 고정 윈도우(5회/15분) 정합성 유지.

        Args:
            email: 식별자 (이메일 주소).
            window: 카운터 TTL (초) — 첫 실패 시 1회만 설정.

        Returns:
            증가 후 현재 시도 횟수.
        """
        key = RedisKey.rate_login_email(email)
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window, nx=True)  # 고정 윈도우: TTL 없을 때만 설정
        results = await pipe.execute()
        return int(results[0])

    async def reset_login_attempts(self, email: str) -> None:
        """로그인 성공 시 시도 횟수 초기화."""
        await self._redis.delete(RedisKey.rate_login_email(email))

    async def revoke_sessions_except(self, user_id: str, except_client_id: str) -> None:
        """현재 세션을 제외한 모든 Redis refresh token 파이프라인으로 일괄 폐기.

        Args:
            user_id: 사용자 UUID 문자열.
            except_client_id: 유지할 현재 세션 client_id.
        """
        client_ids = await self.list_sessions(user_id)
        targets = [cid for cid in client_ids if cid != except_client_id]
        if not targets:
            return

        pipe = self._redis.pipeline()
        for cid in targets:
            pipe.delete(RedisKey.refresh_token(user_id, cid))
            pipe.srem(RedisKey.refresh_index(user_id), cid)
        await pipe.execute()

    # ── 2FA ───────────────────────────────────────────────────────────────────

    async def store_2fa_setup_secret(self, user_id: str, secret: str, ttl: int) -> None:
        """TOTP setup 임시 secret 저장.

        Args:
            user_id: 사용자 UUID 문자열.
            secret: Base32 TOTP secret (평문).
            ttl: TTL 초 (기본 600초 = 10분).
        """
        await self._redis.set(
            RedisKey.two_fa_setup(user_id),
            secret,
            ex=ttl,
        )

    async def get_2fa_setup_secret(self, user_id: str) -> str | None:
        """TOTP setup 임시 secret 조회 (삭제 없음).

        Args:
            user_id: 사용자 UUID 문자열.

        Returns:
            Base32 secret 문자열 또는 None (만료/없음).
        """
        return await self._redis.get(RedisKey.two_fa_setup(user_id))

    async def delete_2fa_setup_secret(self, user_id: str) -> None:
        """TOTP setup 임시 secret 삭제 (활성화 성공 후 호출).

        Args:
            user_id: 사용자 UUID 문자열.
        """
        await self._redis.delete(RedisKey.two_fa_setup(user_id))

    async def get_2fa_fail_count(self, user_id: str) -> int:
        """TOTP 실패 횟수 조회.

        Args:
            user_id: 사용자 UUID 문자열.

        Returns:
            실패 횟수 (없으면 0).
        """
        val = await self._redis.get(RedisKey.two_fa_fail(user_id))
        return int(val) if val else 0

    async def increment_2fa_fail_count(self, user_id: str, ttl: int) -> int:
        """TOTP 실패 횟수 증가 (고정 윈도우).

        Args:
            user_id: 사용자 UUID 문자열.
            ttl: TTL 초 (기본 900초 = 15분).

        Returns:
            증가 후 실패 횟수.
        """
        key = RedisKey.two_fa_fail(user_id)
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        results = await pipe.execute()
        return int(results[0])

    async def reset_2fa_fail_count(self, user_id: str) -> None:
        """TOTP 실패 횟수 초기화 (검증 성공 시).

        Args:
            user_id: 사용자 UUID 문자열.
        """
        await self._redis.delete(RedisKey.two_fa_fail(user_id))

    async def store_2fa_login_pending(
        self, user_id: str, token_hash: str, data: str, ttl: int
    ) -> None:
        """2FA 로그인 임시 토큰 저장 (5분 TTL).

        설계서 §10.1의 `auth:2fa_pending:{user_id}:{token_hash}` 키 패턴 준수.
        조회 시 user_id를 역참조할 수 있도록 인덱스 키도 함께 저장.

        Args:
            user_id: 사용자 UUID 문자열.
            token_hash: SHA-256(temp_token) hex.
            data: JSON 문자열 (user_id, device_info 포함).
            ttl: TTL 초.
        """
        pipe = self._redis.pipeline()
        # 설계서 키: auth:2fa_pending:{user_id}:{token_hash}
        pipe.set(RedisKey.two_fa_pending(user_id, token_hash), data, ex=ttl)
        # 조회용 인덱스: token_hash → user_id (같은 TTL)
        pipe.set(RedisKey.two_fa_pending_idx(token_hash), user_id, ex=ttl)
        await pipe.execute()

    async def get_and_delete_2fa_login_pending(self, token_hash: str) -> str | None:
        """2FA 로그인 임시 토큰 조회 + 삭제 (1회용).

        인덱스 키로 user_id를 찾은 후 설계서 키 패턴으로 GETDEL.

        Args:
            token_hash: SHA-256(temp_token) hex.

        Returns:
            JSON 문자열 또는 None (만료/없음).
        """
        user_id = await self._redis.getdel(RedisKey.two_fa_pending_idx(token_hash))
        if user_id is None:
            return None
        return await self._redis.getdel(RedisKey.two_fa_pending(user_id, token_hash))
