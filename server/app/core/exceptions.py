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
