"""Client(기기 세션) 스키마 — FCM 토큰 등록/조회/삭제."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClientRegisterRequest(BaseModel):
    device_type: Literal["ios", "android", "web"]
    device_name: str | None = Field(default=None, max_length=200)
    fcm_token: str | None = Field(default=None, max_length=500)


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    client_id: uuid.UUID
    device_type: str
    device_name: str | None
    fcm_token: str | None
    is_active: bool
    created_at: datetime
    last_active_at: datetime | None


class ClientListResponse(BaseModel):
    clients: list[ClientResponse]
