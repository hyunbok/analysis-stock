from pydantic import model_validator
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
    OPENAI_TIMEOUT: float = 10.0  # GPT 호출 타임아웃 (초), v1-16 신규

    # Celery
    CELERY_BROKER_URL: str = ""          # 비어있으면 REDIS_URL 기반 DB 1
    CELERY_RESULT_BACKEND: str = ""      # 비어있으면 REDIS_URL 기반 DB 2
    CELERY_WORKER_CONCURRENCY: int = 4   # Worker 동시성

    # Feature Switches
    AI_TRADING_ENABLED: bool = True      # AI 매매 시스템 마스터 스위치
    NEWS_SCRAPER_ENABLED: bool = True    # 뉴스 스크랩 마스터 스위치

    # Monitoring
    SENTRY_DSN: str = ""

    # Circuit Breaker
    CB_FAILURE_THRESHOLD: int = 5           # 연속 실패 허용 횟수
    CB_FAILURE_RATE_THRESHOLD: float = 0.5  # 실패율 임계값
    CB_FAILURE_RATE_WINDOW: int = 30        # 실패율 윈도우 (초)
    CB_RECOVERY_TIMEOUT: int = 60           # OPEN → HALF-OPEN 대기 (초)

    # Exchange Provider
    EXCHANGE_HTTP_TIMEOUT: int = 10         # HTTP 요청 타임아웃 (초)
    EXCHANGE_WS_PING_INTERVAL: int = 30     # WebSocket ping 간격 (초)
    EXCHANGE_WS_RECONNECT_MAX: int = 5      # WS 재연결 최대 시도
    EXCHANGE_WS_RECONNECT_DELAY: float = 1.0  # WS 재연결 초기 대기 (초)

    # TOTP 2FA
    TOTP_ENCRYPTION_KEY: str = ""  # 32바이트 hex (64자) — bytes.fromhex()로 사용
    TOTP_SETUP_TTL: int = 600       # 10분 (setup 세션 TTL)
    TOTP_TEMP_TOKEN_TTL: int = 300  # 5분 (2FA 로그인 임시 토큰 TTL)
    TOTP_FAIL_MAX: int = 5          # TOTP 최대 실패 횟수 (15분 윈도우)

    # FCM Push Notifications
    FCM_SERVER_KEY: str | None = None          # deprecated (v1-21 하위 호환)
    FIREBASE_CREDENTIALS_JSON: str = ""        # 서비스 계정 JSON 문자열 (빈 문자열=비활성)

    # FCM Rate Limiting
    FCM_RATE_LIMIT_PER_MINUTE: int = 10        # 사용자별 분당 최대 발송 건수

    # WebSocket Hub
    WS_MAX_CONNECTIONS: int = 1000
    WS_MAX_CONNECTIONS_PER_USER: int = 5
    WS_MAX_SUBSCRIPTIONS_PER_CONN: int = 50
    WS_HEARTBEAT_INTERVAL: int = 30       # 초 (Heartbeat 확인 주기)
    WS_HEARTBEAT_TIMEOUT: int = 60        # 초 (무응답 연결 강제 종료 기준)

    # OAuth2 (Social Login)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_ID_IOS: str = ""
    GOOGLE_CLIENT_ID_ANDROID: str = ""

    APPLE_APP_BUNDLE_ID: str = ""
    APPLE_WEB_CLIENT_ID: str = ""

    OAUTH_JWKS_CACHE_TTL: int = 3600  # JWKS 공개키 Redis 캐시 TTL (초, 기본 1시간)

    @model_validator(mode="after")
    def _validate_encryption_keys(self) -> "Settings":
        """TOTP_ENCRYPTION_KEY, EXCHANGE_API_KEY_SECRET 형식 검증 — 64자 hex (32바이트 AES-256 키)."""
        for key_name in ("TOTP_ENCRYPTION_KEY", "EXCHANGE_API_KEY_SECRET"):
            key = getattr(self, key_name)
            if key:
                if len(key) != 64:
                    raise ValueError(
                        f"{key_name} must be 64 hex characters (32 bytes). "
                        f"Got {len(key)} characters."
                    )
                try:
                    bytes.fromhex(key)
                except ValueError:
                    raise ValueError(f"{key_name} must be a valid hex string.")
        return self

    @property
    def celery_broker_url(self) -> str:
        """Celery broker URL (Redis DB 1)."""
        if self.CELERY_BROKER_URL:
            return self.CELERY_BROKER_URL
        base = self.REDIS_URL.rstrip("/").rsplit("/", 1)[0]
        return f"{base}/1"

    @property
    def celery_result_backend(self) -> str:
        """Celery result backend URL (Redis DB 2)."""
        if self.CELERY_RESULT_BACKEND:
            return self.CELERY_RESULT_BACKEND
        base = self.REDIS_URL.rstrip("/").rsplit("/", 1)[0]
        return f"{base}/2"

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
