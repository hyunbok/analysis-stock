from datetime import datetime, UTC
from typing import Optional
from uuid import UUID

import pymongo
from beanie import Document, Indexed
from pydantic import Field


class AuditLog(Document):
    user_id: Optional[UUID] = None  # May be absent for login failures
    action: str  # login / logout / password_change / api_key_change / 2fa_toggle
    ip_address: str
    user_agent: str = Field(max_length=500)
    details: Optional[dict] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "audit_logs"
        indexes = [
            pymongo.IndexModel([("user_id", pymongo.ASCENDING)]),
            pymongo.IndexModel([("action", pymongo.ASCENDING)]),
            pymongo.IndexModel([("created_at", pymongo.ASCENDING)]),
        ]
