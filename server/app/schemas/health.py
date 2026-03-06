from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ComponentStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    postgres: Literal["up", "down"]
    mongodb: Literal["up", "down"]
    redis: Literal["up", "down"]


class HealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Literal["healthy", "unhealthy"]
    components: ComponentStatus
    timestamp: datetime
