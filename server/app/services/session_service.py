"""디바이스 세션 관리 서비스 — Client 생성/갱신, 세션 종료."""
from __future__ import annotations

import logging
import uuid

from app.models.user import Client
from app.repositories.client_repository import ClientRepository
from app.services.auth_cache_service import AuthCacheService

logger = logging.getLogger(__name__)


def extract_device_type(user_agent: str) -> str:
    """User-Agent 문자열에서 디바이스 타입 추론.

    Args:
        user_agent: HTTP User-Agent 헤더.

    Returns:
        'ios' | 'android' | 'web'
    """
    ua_lower = user_agent.lower()
    if "iphone" in ua_lower or "ipad" in ua_lower or "ios" in ua_lower:
        return "ios"
    if "android" in ua_lower:
        return "android"
    return "web"


class SessionService:
    """디바이스 세션 관리.

    ClientRepository(PostgreSQL)와 AuthCacheService(Redis)를 조합하여
    세션 생성/갱신/종료를 처리한다.
    """

    def __init__(
        self,
        client_repo: ClientRepository,
        cache: AuthCacheService,
    ) -> None:
        self._repo = client_repo
        self._cache = cache

    async def create_or_update_session(
        self,
        user_id: uuid.UUID,
        device_fingerprint: str | None,
        device_name: str | None,
        device_type: str,
        ip_address: str,
        user_agent: str,
    ) -> tuple[Client, bool]:
        """세션 생성 또는 기존 세션 갱신.

        fingerprint가 있고 동일 디바이스의 활성 세션이 있으면 last_active_at만 갱신한다.
        그 외에는 새 Client를 생성한다.

        Args:
            user_id: 사용자 UUID.
            device_fingerprint: 클라이언트 제공 SHA-256 핑거프린트 (선택).
            device_name: 디바이스 표시 이름 (선택).
            device_type: ios | android | web.
            ip_address: 요청 IP.
            user_agent: HTTP User-Agent.

        Returns:
            (client, is_new_device) 튜플.
            is_new_device=True: 새 디바이스 생성, False: 기존 디바이스 갱신.
        """
        if device_fingerprint:
            existing = await self._repo.get_by_user_and_fingerprint(
                user_id, device_fingerprint
            )
            if existing is not None:
                await self._repo.update_last_active(existing.id)
                return existing, False

        client = await self._repo.create(
            user_id,
            device_type=device_type,
            device_name=device_name,
            user_agent=user_agent,
            ip_address=ip_address,
            device_fingerprint=device_fingerprint,
        )
        return client, True

    async def list_sessions(self, user_id: uuid.UUID) -> list[Client]:
        """사용자의 활성 세션 목록 조회.

        Args:
            user_id: 사용자 UUID.

        Returns:
            is_active=True인 Client 리스트.
        """
        return await self._repo.get_by_user(user_id)

    async def revoke_session(
        self, user_id: uuid.UUID, client_id: uuid.UUID
    ) -> None:
        """개별 세션 종료.

        Client.is_active=False + Redis refresh token 즉시 폐기.

        Args:
            user_id: 사용자 UUID.
            client_id: 종료할 Client UUID.

        Raises:
            AppError(SESSION_NOT_FOUND): client_id가 없거나 다른 사용자 소유.
        """
        from app.core.exceptions import AuthErrors

        client = await self._repo.get_by_id(client_id)
        if client is None or client.user_id != user_id or not client.is_active:
            raise AuthErrors.session_not_found()

        await self._repo.deactivate(client_id)
        await self._cache.revoke_refresh_token(str(user_id), str(client_id))

    async def revoke_all_sessions(
        self,
        user_id: uuid.UUID,
        except_client_id: uuid.UUID | None = None,
    ) -> int:
        """모든 세션 종료 (현재 세션 제외 옵션).

        Args:
            user_id: 사용자 UUID.
            except_client_id: 현재 세션 Client UUID (제외할 세션).

        Returns:
            종료된 세션 수.
        """
        count = await self._repo.deactivate_all(user_id, except_client_id)

        # Redis refresh tokens도 일괄 폐기
        if except_client_id is None:
            await self._cache.revoke_all_sessions(str(user_id))
        else:
            await self._cache.revoke_sessions_except(str(user_id), str(except_client_id))

        return count
