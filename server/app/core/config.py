from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "CoinTrader API"
    ENV: str = "dev"  # dev, staging, prod
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

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

    # Auth (JWT)
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # Encryption (for exchange API keys)
    EXCHANGE_API_KEY_SECRET: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Monitoring
    SENTRY_DSN: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
