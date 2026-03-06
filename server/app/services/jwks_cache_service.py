"""JWKS 공개키 Redis 캐시 서비스."""
from __future__ import annotations

import json
import logging

import httpx
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import AuthErrors

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "oauth:jwks"


class JwksCacheService:
    """JWKS 공개키 Redis 캐시.

    캐시 키: oauth:jwks:{provider}
    TTL: settings.OAUTH_JWKS_CACHE_TTL (기본 3600초)
    저장 형식: JWKS JSON 원문 string
    """

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    async def get_public_key(self, provider: str, kid: str, jwks_url: str) -> dict:
        """JWKS에서 kid에 해당하는 JWK dict 반환.

        캐시 HIT + kid 없음(키 순환) 시 명시적 DEL 후 원격 재조회 1회 수행.

        Args:
            provider: "google" | "apple"
            kid: JWT header의 kid 클레임.
            jwks_url: JWKS 조회 URL (클래스 상수에서 전달, SSRF 방지).

        Returns:
            JWK dict (python-jose jwt.decode에 직접 전달 가능).

        Raises:
            AppError(INVALID_OAUTH_TOKEN): kid에 해당하는 키 없음 (재시도 후에도).
            AppError(OAUTH_PROVIDER_UNAVAILABLE): JWKS HTTP 조회 실패.
        """
        cache_key = f"{_CACHE_KEY_PREFIX}:{provider}"

        # 1차 시도: 캐시 조회
        raw = await self._redis.get(cache_key)
        if raw is not None:
            jwks = json.loads(raw)
            key = self._extract_key(jwks, kid)
            if key is not None:
                return key
            # 캐시 HIT이지만 kid 없음 (키 순환 감지) → 명시적 DEL 후 재조회
            await self.invalidate(provider)

        # 캐시 미스 또는 키 순환 → 원격 재조회
        jwks = await self._fetch_and_cache(cache_key, jwks_url)
        key = self._extract_key(jwks, kid)
        if key is None:
            raise AuthErrors.invalid_oauth_token()
        return key

    async def _fetch_and_cache(self, cache_key: str, jwks_url: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(jwks_url)
                resp.raise_for_status()
                jwks = resp.json()
        except Exception as e:
            logger.error("jwks_fetch_failed", extra={"url": jwks_url, "error": str(e)})
            raise AuthErrors.oauth_provider_unavailable()

        await self._redis.setex(
            cache_key,
            self._settings.OAUTH_JWKS_CACHE_TTL,
            json.dumps(jwks),
        )
        return jwks

    @staticmethod
    def _extract_key(jwks: dict, kid: str) -> dict | None:
        """JWKS JSON에서 kid 일치하는 JWK dict 반환. 없으면 None."""
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                return key_data
        return None

    async def invalidate(self, provider: str) -> None:
        """캐시 강제 무효화 (키 순환 감지 시 사용)."""
        await self._redis.delete(f"{_CACHE_KEY_PREFIX}:{provider}")
