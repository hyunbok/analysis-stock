"""세션 관리 Pydantic 스키마."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionResponse(BaseModel):
    """단일 세션(디바이스) 응답."""

    model_config = ConfigDict(from_attributes=True)

    client_id: uuid.UUID
    device_type: str
    device_name: str | None
    ip_address: str | None
    user_agent: str | None
    last_active_at: datetime | None
    created_at: datetime
    is_current: bool = False  # 현재 요청의 client_id와 일치 여부 (API 레이어에서 설정)

    @classmethod
    def from_client(cls, client: object, current_client_id: uuid.UUID | None = None) -> "SessionResponse":
        """Client ORM 모델에서 SessionResponse 생성."""
        return cls(
            client_id=client.id,  # type: ignore[attr-defined]
            device_type=client.device_type,  # type: ignore[attr-defined]
            device_name=client.device_name,  # type: ignore[attr-defined]
            ip_address=client.ip_address,  # type: ignore[attr-defined]
            user_agent=client.user_agent,  # type: ignore[attr-defined]
            last_active_at=client.last_active_at,  # type: ignore[attr-defined]
            created_at=client.created_at,  # type: ignore[attr-defined]
            is_current=(current_client_id is not None and client.id == current_client_id),  # type: ignore[attr-defined]
        )


class SessionListResponse(BaseModel):
    """세션 목록 응답."""

    sessions: list[SessionResponse]


class LogoutAllResponse(BaseModel):
    """전체 로그아웃 응답."""

    message: str = "모든 세션에서 로그아웃되었습니다."
    revoked_count: int
