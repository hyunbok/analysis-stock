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
        """인증 코드 검증 후 삭제 (1회용). 일치 여부 반환."""
        stored = await self._redis.get(RedisKey.email_verify(email))
        if stored is None or stored != code:
            return False
        await self._redis.delete(RedisKey.email_verify(email))
        return True

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
