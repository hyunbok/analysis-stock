"""도메인 비즈니스 로직 예외 클래스 정의."""
from __future__ import annotations


class AppError(Exception):
    """도메인 비즈니스 로직 에러."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        self.status_code = http_status  # 테스트 호환성 별칭
        super().__init__(message)


class AuthErrors:
    """인증 도메인 에러 팩토리."""

    @staticmethod
    def email_already_exists() -> AppError:
        return AppError("EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다.", 409)

    @staticmethod
    def nickname_taken() -> AppError:
        return AppError("NICKNAME_TAKEN", "이미 사용 중인 닉네임입니다.", 409)

    @staticmethod
    def invalid_credentials() -> AppError:
        return AppError("INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.", 401)

    @staticmethod
    def email_not_verified() -> AppError:
        return AppError("EMAIL_NOT_VERIFIED", "이메일 인증이 필요합니다.", 403)

    @staticmethod
    def account_deleted() -> AppError:
        return AppError("ACCOUNT_DELETED", "삭제 예약된 계정입니다.", 410)

    @staticmethod
    def invalid_refresh_token() -> AppError:
        return AppError("INVALID_REFRESH_TOKEN", "유효하지 않은 Refresh Token입니다.", 401)

    @staticmethod
    def unauthorized() -> AppError:
        return AppError("UNAUTHORIZED", "인증이 필요합니다.", 401)

    @staticmethod
    def user_not_found() -> AppError:
        return AppError("USER_NOT_FOUND", "사용자를 찾을 수 없습니다.", 404)

    @staticmethod
    def invalid_verify_code() -> AppError:
        return AppError("INVALID_VERIFY_CODE", "인증 코드가 올바르지 않거나 만료되었습니다.", 400)

    @staticmethod
    def email_already_verified() -> AppError:
        return AppError("EMAIL_ALREADY_VERIFIED", "이미 인증 완료된 이메일입니다.", 409)

    @staticmethod
    def email_send_failed() -> AppError:
        return AppError("EMAIL_SEND_FAILED", "이메일 발송에 실패했습니다. 잠시 후 재시도해주세요.", 502)

    @staticmethod
    def login_rate_limit() -> AppError:
        return AppError("LOGIN_RATE_LIMIT", "로그인 시도 횟수를 초과했습니다. 15분 후 재시도해주세요.", 429)

    @staticmethod
    def invalid_oauth_token() -> AppError:
        """Google/Apple id_token 서명 검증 실패 또는 만료."""
        return AppError("INVALID_OAUTH_TOKEN", "유효하지 않은 OAuth 토큰입니다.", 401)

    @staticmethod
    def oauth_email_required() -> AppError:
        """OAuth 토큰에 이메일이 포함되지 않아 처리 불가 (Google 이메일 공개 미허용)."""
        return AppError(
            "OAUTH_EMAIL_REQUIRED",
            "소셜 로그인에 이메일 제공이 필요합니다. 설정에서 이메일 공개 권한을 허용해주세요.",
            422,
        )

    @staticmethod
    def oauth_provider_unavailable() -> AppError:
        """JWKS 조회 실패 등 OAuth 공급자 서버 오류."""
        return AppError(
            "OAUTH_PROVIDER_UNAVAILABLE",
            "소셜 인증 서버에 일시적으로 연결할 수 없습니다. 잠시 후 재시도해주세요.",
            502,
        )

    @staticmethod
    def totp_already_enabled() -> AppError:
        """2FA 이미 활성화 상태에서 setup 시도."""
        return AppError("TOTP_ALREADY_ENABLED", "2FA가 이미 활성화되어 있습니다.", 409)

    @staticmethod
    def totp_not_enabled() -> AppError:
        """2FA 미활성 상태에서 disable/검증 시도."""
        return AppError("TOTP_NOT_ENABLED", "2FA가 활성화되어 있지 않습니다.", 400)

    @staticmethod
    def totp_setup_required() -> AppError:
        """setup 없이 verify 호출 또는 임시 secret 만료."""
        return AppError("TOTP_SETUP_REQUIRED", "2FA 설정이 필요합니다. 다시 시도해주세요.", 400)

    @staticmethod
    def invalid_totp_code() -> AppError:
        """TOTP 코드 또는 백업 코드 불일치."""
        return AppError("INVALID_TOTP_CODE", "유효하지 않은 인증 코드입니다.", 400)

    @staticmethod
    def invalid_temp_token() -> AppError:
        """2FA 로그인 임시 토큰 만료/불일치."""
        return AppError("INVALID_TEMP_TOKEN", "유효하지 않은 임시 토큰입니다.", 401)

    @staticmethod
    def session_not_found() -> AppError:
        """세션(client_id) 없음."""
        return AppError("SESSION_NOT_FOUND", "세션을 찾을 수 없습니다.", 404)


class CoinErrors:
    """코인/관심 코인 도메인 에러 팩토리."""

    @staticmethod
    def not_found() -> AppError:
        return AppError("COIN_NOT_FOUND", "코인을 찾을 수 없습니다.", 404)

    @staticmethod
    def watchlist_not_found() -> AppError:
        return AppError("WATCHLIST_NOT_FOUND", "관심 코인을 찾을 수 없습니다.", 404)

    @staticmethod
    def watchlist_duplicate() -> AppError:
        return AppError("WATCHLIST_DUPLICATE", "이미 관심 코인에 추가되어 있습니다.", 409)

    @staticmethod
    def watchlist_access_denied() -> AppError:
        return AppError("WATCHLIST_ACCESS_DENIED", "접근 권한이 없습니다.", 403)

    @staticmethod
    def watchlist_reorder_invalid() -> AppError:
        return AppError("WATCHLIST_REORDER_INVALID", "정렬 변경 대상이 올바르지 않습니다.", 400)

    @staticmethod
    def exchange_account_mismatch() -> AppError:
        return AppError("EXCHANGE_ACCOUNT_MISMATCH", "본인 소유 거래소 계정이 아닙니다.", 403)


class ExchangeErrors:
    """거래소 도메인 AppError 팩토리 (HTTP 응답용)."""

    @staticmethod
    def circuit_open(exchange: str) -> AppError:
        """Circuit Breaker OPEN 상태."""
        return AppError(
            "EXCHANGE_CIRCUIT_OPEN",
            f"{exchange} 거래소가 일시적으로 차단되었습니다. 잠시 후 재시도해주세요.",
            503,
        )

    @staticmethod
    def rate_limited(exchange: str, retry_after_seconds: int | None = None) -> AppError:
        """Rate Limit 초과."""
        msg = "거래소 요청 횟수 제한을 초과했습니다."
        if retry_after_seconds:
            msg += f" {retry_after_seconds}초 후 재시도해주세요."
        return AppError("EXCHANGE_RATE_LIMITED", msg, 429)

    @staticmethod
    def auth_failed(exchange: str) -> AppError:
        """API 키 인증 실패."""
        return AppError(
            "EXCHANGE_AUTH_FAILED",
            f"{exchange} API 키 인증에 실패했습니다. API 키와 시크릿을 확인해주세요.",
            401,
        )

    @staticmethod
    def permission_denied(exchange: str, missing: str) -> AppError:
        """API 키 권한 부족."""
        return AppError(
            "EXCHANGE_PERMISSION_DENIED",
            f"{exchange} API 키에 필요한 권한({missing})이 없습니다.",
            403,
        )

    @staticmethod
    def insufficient_balance() -> AppError:
        """잔고 부족."""
        return AppError("EXCHANGE_INSUFFICIENT_BALANCE", "잔고가 부족합니다.", 400)

    @staticmethod
    def order_failed(exchange: str, reason: str) -> AppError:
        """주문 실패."""
        return AppError("EXCHANGE_ORDER_FAILED", f"주문 처리 실패: {reason}", 400)

    @staticmethod
    def unavailable(exchange: str) -> AppError:
        """거래소 서비스 불가."""
        return AppError(
            "EXCHANGE_UNAVAILABLE",
            f"{exchange} 거래소에 연결할 수 없습니다. 잠시 후 재시도해주세요.",
            503,
        )

    @staticmethod
    def invalid_api_key() -> AppError:
        """유효하지 않은 API 키."""
        return AppError("EXCHANGE_INVALID_API_KEY", "유효하지 않은 API 키입니다.", 422)

    @staticmethod
    def account_not_found() -> AppError:
        """거래소 계정 미등록."""
        return AppError(
            "EXCHANGE_ACCOUNT_NOT_FOUND", "거래소 계정이 등록되지 않았습니다.", 404
        )

    @staticmethod
    def duplicate_exchange_account(exchange: str) -> AppError:
        """이미 등록된 거래소 계정."""
        return AppError(
            "EXCHANGE_DUPLICATE_ACCOUNT",
            f"{exchange} 거래소 계정이 이미 등록되어 있습니다.",
            409,
        )

    @staticmethod
    def encryption_key_not_configured() -> AppError:
        """암호화 키 미설정."""
        return AppError(
            "EXCHANGE_ENCRYPTION_NOT_CONFIGURED",
            "거래소 API 키 암호화 설정이 완료되지 않았습니다.",
            500,
        )

    @staticmethod
    def key_pair_required() -> AppError:
        """API 키 쌍 불완전 제공."""
        return AppError(
            "EXCHANGE_KEY_PAIR_REQUIRED",
            "API 키와 시크릿은 함께 변경해야 합니다.",
            400,
        )


class RegimeErrors:
    """장세 분석 도메인 에러 팩토리."""

    @staticmethod
    def insufficient_indicators() -> AppError:
        """장세 분류에 필요한 지표 데이터 부족 (활성 규칙 < 2개)."""
        return AppError(
            "REGIME_INSUFFICIENT_INDICATORS",
            "장세 분석에 필요한 지표 데이터가 부족합니다.",
            422,
        )

    @staticmethod
    def gpt_validation_failed() -> AppError:
        """GPT 검증 API 호출 실패 (로깅용, 실제로는 graceful fallback)."""
        return AppError(
            "REGIME_GPT_VALIDATION_FAILED",
            "AI 보조 검증에 실패했습니다. 규칙 기반 결과를 사용합니다.",
            200,
        )

    @staticmethod
    def analysis_failed() -> AppError:
        """장세 분석 전체 실패."""
        return AppError(
            "REGIME_ANALYSIS_FAILED",
            "장세 분석에 실패했습니다. 잠시 후 재시도해주세요.",
            500,
        )


class IndicatorErrors:
    """기술적 지표 도메인 에러 팩토리."""

    @staticmethod
    def insufficient_candles(required: int, actual: int) -> AppError:
        return AppError(
            "INSUFFICIENT_CANDLES",
            f"지표 계산에 필요한 캔들이 부족합니다. 필요: {required}, 현재: {actual}",
            422,
        )

    @staticmethod
    def calculation_failed() -> AppError:
        return AppError(
            "INDICATOR_CALCULATION_FAILED",
            "지표 계산에 실패했습니다. 잠시 후 재시도해주세요.",
            500,
        )


class PortfolioErrors:
    """포트폴리오 관련 에러 팩토리."""

    @staticmethod
    def exchange_account_not_owned() -> AppError:
        """본인 소유가 아닌 거래소 계정 접근 시."""
        return AppError(
            code="PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED",
            message="본인 소유 거래소 계정이 아닙니다.",
            http_status=403,
        )

    @staticmethod
    def no_exchange_accounts() -> AppError:
        """등록된 거래소 계정이 없을 때."""
        return AppError(
            code="PORTFOLIO_NO_EXCHANGE_ACCOUNTS",
            message="등록된 거래소 계정이 없습니다.",
            http_status=404,
        )

    @staticmethod
    def balance_fetch_failed(exchange: str) -> AppError:
        """거래소 잔고 API 호출 실패."""
        return AppError(
            code="PORTFOLIO_BALANCE_FETCH_FAILED",
            message=f"{exchange} 잔고 조회에 실패했습니다.",
            http_status=503,
        )

    @staticmethod
    def exchange_unavailable(exchange: str) -> AppError:
        """거래소 연결 불가 (Circuit Breaker open 등)."""
        return AppError(
            code="PORTFOLIO_EXCHANGE_UNAVAILABLE",
            message=f"{exchange} 거래소에 연결할 수 없습니다.",
            http_status=503,
        )


class PriceAlertErrors:
    """가격 알림 도메인 에러 팩토리."""

    @staticmethod
    def not_found() -> AppError:
        return AppError("PRICE_ALERT_NOT_FOUND", "가격 알림을 찾을 수 없습니다.", 404)

    @staticmethod
    def access_denied() -> AppError:
        return AppError("PRICE_ALERT_ACCESS_DENIED", "접근 권한이 없습니다.", 403)

    @staticmethod
    def coin_not_found() -> AppError:
        return AppError("PRICE_ALERT_COIN_NOT_FOUND", "등록된 코인을 찾을 수 없습니다.", 404)

    @staticmethod
    def exchange_account_not_owned() -> AppError:
        return AppError("PRICE_ALERT_ACCOUNT_NOT_OWNED", "본인 소유 거래소 계정이 아닙니다.", 403)

    @staticmethod
    def already_triggered() -> AppError:
        """이미 트리거된 알림은 재활성화 불가."""
        return AppError("PRICE_ALERT_ALREADY_TRIGGERED", "이미 발동된 알림은 재활성화할 수 없습니다.", 409)

    @staticmethod
    def max_exceeded() -> AppError:
        return AppError("PRICE_ALERT_MAX_EXCEEDED", "사용자당 최대 50개의 가격 알림만 생성 가능합니다.", 400)


class NotificationErrors:
    """알림 도메인 에러 팩토리."""

    @staticmethod
    def not_found() -> AppError:
        return AppError("NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없습니다.", 404)

    @staticmethod
    def access_denied() -> AppError:
        return AppError("NOTIFICATION_ACCESS_DENIED", "접근 권한이 없습니다.", 403)


class OrderErrors:
    """주문 도메인 에러 팩토리."""

    @staticmethod
    def not_found() -> AppError:
        return AppError("ORDER_NOT_FOUND", "주문을 찾을 수 없습니다.", 404)

    @staticmethod
    def invalid_status_transition(current: str, target: str) -> AppError:
        return AppError(
            "INVALID_ORDER_TRANSITION",
            f"주문 상태 전이 불가: {current} → {target}",
            409,
        )

    @staticmethod
    def cannot_cancel(status: str) -> AppError:
        return AppError(
            "ORDER_CANNOT_CANCEL",
            f"취소할 수 없는 상태입니다: {status}",
            422,
        )

    @staticmethod
    def insufficient_balance() -> AppError:
        return AppError("INSUFFICIENT_BALANCE", "잔고가 부족합니다.", 422)

    @staticmethod
    def exchange_order_failed(detail: str = "") -> AppError:
        """거래소 주문 처리 실패. detail은 로그에만 기록하고 클라이언트에 노출하지 않는다."""
        return AppError(
            "EXCHANGE_ORDER_FAILED",
            "거래소 주문 처리에 실패했습니다. 잠시 후 재시도해주세요.",
            502,
        )

    @staticmethod
    def exchange_unavailable() -> AppError:
        return AppError(
            "EXCHANGE_UNAVAILABLE",
            "거래소에 일시적으로 연결할 수 없습니다. 잠시 후 재시도해주세요.",
            503,
        )
