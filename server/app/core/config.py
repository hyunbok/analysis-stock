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
    REDIS_PUBSUB_URL: str = ""  # 비어있으면 REDIS_URL 사용

    # Rate Limiting
    RATE_LIMIT_API_ANON: int = 60       # 비인증 분당 요청 수
    RATE_LIMIT_API_AUTH: int = 120      # 인증 사용자 분당 요청 수
    RATE_LIMIT_LOGIN_MAX: int = 5       # 로그인 시도 최대 횟수
    RATE_LIMIT_LOGIN_WINDOW: int = 900  # 로그인 제한 윈도우 (초)

    # Auth (JWT)
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # Encryption (for exchange API keys)
    EXCHANGE_API_KEY_SECRET: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    # SMTP (이메일 발송)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@cointrader.io"
    SMTP_FROM_NAME: str = "CoinTrader"
    SMTP_STARTTLS: bool = True

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Monitoring
    SENTRY_DSN: str = ""

    # OAuth2 (Social Login)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_ID_IOS: str = ""
    GOOGLE_CLIENT_ID_ANDROID: str = ""

    APPLE_APP_BUNDLE_ID: str = ""
    APPLE_WEB_CLIENT_ID: str = ""

    OAUTH_JWKS_CACHE_TTL: int = 3600  # JWKS 공개키 Redis 캐시 TTL (초, 기본 1시간)

    @property
    def google_allowed_audiences(self) -> list[str]:
        """Google aud 검증에 허용할 Client ID 목록."""
        return [v for v in [
            self.GOOGLE_CLIENT_ID,
            self.GOOGLE_CLIENT_ID_IOS,
            self.GOOGLE_CLIENT_ID_ANDROID,
        ] if v]

    @property
    def apple_allowed_audiences(self) -> list[str]:
        """Apple aud 검증에 허용할 audience 목록."""
        return [v for v in [
            self.APPLE_APP_BUNDLE_ID,
            self.APPLE_WEB_CLIENT_ID,
        ] if v]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
