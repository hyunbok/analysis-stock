"""WebSocket 전용 JWT 인증 함수 — FastAPI DI 없는 독립 인증."""
from __future__ import annotations

import logging
import uuid

from jose import JWTError

from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


async def authenticate_ws(token: str) -> User | None:
    """WebSocket 연결 시 JWT 토큰 인증.

    REST의 get_current_user()는 Depends() 기반이라 WS에서 직접 사용 불가.
    이 함수는 동일한 로직을 FastAPI DI 없이 독립적으로 수행한다.

    Args:
        token: Query param으로 전달된 access token 문자열.

    Returns:
        인증 성공 시 User 인스턴스, 실패(만료/변조/없는 사용자) 시 None.
    """
    try:
        payload = decode_access_token(token)
        user_id_str: str = payload.get("sub", "")
        if not user_id_str:
            return None
        user_id = uuid.UUID(user_id_str)
    except (JWTError, ValueError):
        logger.debug("WS auth failed: invalid or expired token")
        return None

    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        user = await repo.get_by_id(user_id)

    if user is None or user.soft_deleted_at is not None:
        return None

    return user
