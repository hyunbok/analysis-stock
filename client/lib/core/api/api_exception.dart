import 'package:freezed_annotation/freezed_annotation.dart';

part 'api_exception.freezed.dart';

/// API 호출 실패 시 발생하는 예외 계층.
///
/// 서버 에러 코드 예: EMAIL_ALREADY_EXISTS, INVALID_CREDENTIALS
/// Dio ErrorInterceptor에서 DioException → ApiException으로 변환된다.
@freezed
class ApiException with _$ApiException implements Exception {
  const factory ApiException.server({
    required String code,
    required String message,
    int? statusCode,
    String? correlationId,
  }) = ServerException;

  const factory ApiException.network({required String message}) =
      NetworkException;

  const factory ApiException.requestTimeout() = RequestTimeoutException;

  const factory ApiException.unauthorized() = UnauthorizedException;

  const factory ApiException.unknown({required Object error}) =
      UnknownException;
}
