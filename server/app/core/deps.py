from typing import Annotated, AsyncGenerator

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis

# Type aliases for dependency injection
DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]

# Auth dependencies will be added here:
# CurrentUser = Annotated[User, Depends(get_current_user)]
# CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
