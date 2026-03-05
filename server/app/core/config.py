from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "CoinTrader API"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    ALLOWED_ORIGINS: List[str] = []

    # PostgreSQL
    DATABASE_URL: str = "postgresql+asyncpg://cointrader:password@localhost:5432/cointrader"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10

    # MongoDB
    MONGODB_URL: str = "mongodb://cointrader:password@localhost:27017/cointrader?authSource=admin"
    MONGODB_DB_NAME: str = "cointrader"
    MONGODB_MAX_POOL_SIZE: int = 20

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # Encryption (for exchange API keys)
    ENCRYPTION_KEY: str = "change-me-in-production-32bytes!"

    # OpenAI
    OPENAI_API_KEY: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
