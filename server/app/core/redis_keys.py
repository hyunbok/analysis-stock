"""Redis 키 패턴, TTL 상수, Pub/Sub 채널명 정의."""


class RedisTTL:
    """Redis TTL 상수 (초 단위)"""

    # Auth
    REFRESH_TOKEN = 14 * 24 * 3600  # 14일
    EMAIL_VERIFY = 10 * 60          # 10분
    PASSWORD_RESET = 3600           # 1시간
    TWO_FA_SETUP = 10 * 60          # 10분 (TOTP 설정 중 임시 비밀키)
    TWO_FA_PENDING = 5 * 60         # 5분 (로그인 2단계 임시 상태)
    TWO_FA_FAIL = 15 * 60           # 15분 (TOTP 실패 카운터 윈도우)

    # Rate Limiting
    RATE_WINDOW = 60                # 1분
    LOGIN_RATE = 15 * 60            # 15분

    # Market Data
    TICKER = 10                     # 10초
    CANDLES = 30                    # 30초
    ORDERBOOK = 5                   # 5초

    # AI/Analysis
    INDICATORS_SHORT = 60           # 1분 (1m 타임프레임)
    INDICATORS_LONG = 600           # 10분 (1h+ 타임프레임)
    REGIME = 300                    # 5분
    AI_DECISION = 300               # 5분
    NEWS_SENTIMENT = 30 * 60        # 30분
    AI_LAST_RUN = 10 * 60           # 10분

    # Notifications
    UNREAD_COUNT = 3600             # 1시간


class RedisKey:
    """Redis 키 생성 헬퍼 — 타입 안전 키 생성"""

    # ── Auth ──────────────────────────────────────────────────────────────────

    @staticmethod
    def refresh_token(user_id: str, client_id: str) -> str:
        return f"auth:refresh:{user_id}:{client_id}"

    @staticmethod
    def refresh_index(user_id: str) -> str:
        return f"auth:refresh_index:{user_id}"

    @staticmethod
    def email_verify(email: str) -> str:
        return f"auth:email_verify:{email}"

    @staticmethod
    def password_reset(token: str) -> str:
        return f"auth:password_reset:{token}"

    @staticmethod
    def two_fa_setup(user_id: str) -> str:
        """TOTP setup 중 임시 비밀키 저장 (10분 TTL)."""
        return f"auth:2fa_setup:{user_id}"

    @staticmethod
    def two_fa_pending(user_id: str, temp_id: str) -> str:
        """로그인 2단계 대기 상태 — 기기 정보 임시 저장 (5분 TTL)."""
        return f"auth:2fa_pending:{user_id}:{temp_id}"

    @staticmethod
    def two_fa_fail(user_id: str) -> str:
        """TOTP 코드 실패 카운터 (15분 고정 윈도우, 최대 5회)."""
        return f"auth:2fa_fail:{user_id}"

    @staticmethod
    def two_fa_pending_idx(token_hash: str) -> str:
        """2FA 로그인 임시 토큰 인덱스 — token_hash → user_id 역참조용."""
        return f"auth:2fa_pending_idx:{token_hash}"

    # ── Rate Limiting ─────────────────────────────────────────────────────────

    @staticmethod
    def rate_api_ip(ip: str) -> str:
        return f"rate:api:{ip}"

    @staticmethod
    def rate_api_user(user_id: str) -> str:
        return f"rate:api:{user_id}"

    @staticmethod
    def rate_exchange(exchange: str, user_id: str) -> str:
        return f"rate:exchange:{exchange}:{user_id}"

    @staticmethod
    def rate_login(ip: str) -> str:
        return f"rate:login:{ip}"

    @staticmethod
    def rate_login_email(email: str) -> str:
        return f"rate:login:{email}"

    # ── Market Data ───────────────────────────────────────────────────────────

    @staticmethod
    def ticker(exchange: str, market: str) -> str:
        return f"ticker:{exchange}:{market}"

    @staticmethod
    def candles(exchange: str, market: str, timeframe: str, count: int) -> str:
        return f"candles:{exchange}:{market}:{timeframe}:{count}"

    @staticmethod
    def orderbook(exchange: str, market: str) -> str:
        return f"orderbook:{exchange}:{market}"

    # ── AI/Analysis ───────────────────────────────────────────────────────────

    @staticmethod
    def indicators(exchange: str, market: str, timeframe: str) -> str:
        return f"indicators:{exchange}:{market}:{timeframe}"

    @staticmethod
    def regime(exchange: str, market: str) -> str:
        return f"regime:{exchange}:{market}"

    @staticmethod
    def ai_decision(user_id: str, market: str) -> str:
        return f"ai_decision:{user_id}:{market}:latest"

    @staticmethod
    def news_sentiment(coin: str) -> str:
        return f"ai:news_sentiment:{coin}"

    @staticmethod
    def ai_last_run(user_id: str, coin: str) -> str:
        return f"ai:last_run:{user_id}:{coin}"

    # ── Notifications ─────────────────────────────────────────────────────────

    @staticmethod
    def unread_count(user_id: str) -> str:
        return f"notifications:unread_count:{user_id}"


class PubSubChannel:
    """Pub/Sub 채널명 생성 헬퍼"""

    @staticmethod
    def ticker(exchange: str, market: str) -> str:
        return f"ch:ticker:{exchange}:{market}"

    @staticmethod
    def orderbook(exchange: str, market: str) -> str:
        return f"ch:orderbook:{exchange}:{market}"

    @staticmethod
    def ai_signal(user_id: str) -> str:
        return f"ch:ai_signal:{user_id}"

    @staticmethod
    def notification(user_id: str) -> str:
        return f"ch:notification:{user_id}"

    @staticmethod
    def price_alert(user_id: str) -> str:
        return f"ch:price_alert:{user_id}"

    @staticmethod
    def trades(exchange: str, market: str) -> str:
        return f"ch:trades:{exchange}:{market}"

    @staticmethod
    def my_orders(user_id: str) -> str:
        return f"ch:my_orders:{user_id}"

    @staticmethod
    def system() -> str:
        return "ch:system"
