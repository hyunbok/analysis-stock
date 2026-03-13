"""도메인 비즈니스 로직 예외 클래스 정의."""
from __future__ import annotations


class AppError(Exception):
    """도메인 비즈니스 로직 에러."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
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
