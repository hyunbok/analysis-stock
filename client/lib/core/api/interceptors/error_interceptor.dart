import 'package:dio/dio.dart';

import '../api_exception.dart';

/// 서버 에러 응답을 [ApiException]으로 변환한다.
///
/// 변환 규칙:
/// - `response.data['error'] != null` → [ServerException]
/// - connection/receive/send timeout      → [RequestTimeoutException]
/// - network unreachable                  → [NetworkException]
/// - 그 외                                 → 그대로 전파
class ErrorInterceptor extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final apiException = _toApiException(err);
    if (apiException != null) {
      handler.reject(
        DioException(
          requestOptions: err.requestOptions,
          response: err.response,
          error: apiException,
          type: err.type,
          message: err.message,
          stackTrace: err.stackTrace,
        ),
      );
    } else {
      handler.next(err);
    }
  }

  ApiException? _toApiException(DioException err) {
    switch (err.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.sendTimeout:
        return const ApiException.requestTimeout();

      case DioExceptionType.connectionError:
        return ApiException.network(
          message: err.message ?? 'Network error',
        );

      default:
        final data = err.response?.data;
        if (data is Map<String, dynamic> && data['error'] != null) {
          final errorData = data['error'] as Map<String, dynamic>;
          return ApiException.server(
            code: errorData['code'] as String? ?? 'UNKNOWN',
            message: errorData['message'] as String? ?? 'Unknown error',
            statusCode: err.response?.statusCode,
            correlationId: errorData['correlation_id'] as String?,
          );
        }
        return null;
    }
  }
}
