import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coin_trader/core/api/api_exception.dart';
import 'package:coin_trader/core/api/interceptors/error_interceptor.dart';

/// ErrorInterceptor 테스트용 핸들러.
/// [reject]된 에러와 [next]로 전달된 에러를 각각 캡처한다.
class _CaptureHandler extends ErrorInterceptorHandler {
  DioException? rejected;
  DioException? nexted;

  @override
  void reject(DioException err, {bool callFollowingErrorInterceptor = false}) {
    rejected = err;
  }

  @override
  void next(DioException err) {
    nexted = err;
  }
}

RequestOptions _opts() => RequestOptions(path: '/test');

DioException _makeDioException({
  DioExceptionType type = DioExceptionType.unknown,
  Response<dynamic>? response,
  String? message,
}) {
  return DioException(
    requestOptions: _opts(),
    type: type,
    response: response,
    message: message,
  );
}

void main() {
  late ErrorInterceptor interceptor;
  late _CaptureHandler handler;

  setUp(() {
    interceptor = ErrorInterceptor();
    handler = _CaptureHandler();
  });

  group('ErrorInterceptor — 타임아웃', () {
    test('connectionTimeout → RequestTimeoutException', () {
      final err = _makeDioException(type: DioExceptionType.connectionTimeout);
      interceptor.onError(err, handler);

      expect(handler.rejected, isNotNull);
      expect(handler.rejected!.error, isA<ApiException>());
      expect(
        handler.rejected!.error,
        const ApiException.requestTimeout(),
      );
    });

    test('receiveTimeout → RequestTimeoutException', () {
      final err = _makeDioException(type: DioExceptionType.receiveTimeout);
      interceptor.onError(err, handler);

      expect(handler.rejected!.error, const ApiException.requestTimeout());
    });

    test('sendTimeout → RequestTimeoutException', () {
      final err = _makeDioException(type: DioExceptionType.sendTimeout);
      interceptor.onError(err, handler);

      expect(handler.rejected!.error, const ApiException.requestTimeout());
    });
  });

  group('ErrorInterceptor — 네트워크 오류', () {
    test('connectionError → NetworkException', () {
      final err = _makeDioException(
        type: DioExceptionType.connectionError,
        message: 'Failed to connect',
      );
      interceptor.onError(err, handler);

      expect(
        handler.rejected!.error,
        isA<NetworkException>().having(
          (e) => e.message,
          'message',
          contains('Failed to connect'),
        ),
      );
    });
  });

  group('ErrorInterceptor — 서버 에러 응답', () {
    test('error.code + error.message → ServerException', () {
      final response = Response<dynamic>(
        requestOptions: _opts(),
        statusCode: 400,
        data: {
          'error': {
            'code': 'EMAIL_ALREADY_EXISTS',
            'message': '이미 사용 중인 이메일입니다.',
          },
        },
      );
      final err = _makeDioException(
        type: DioExceptionType.badResponse,
        response: response,
      );
      interceptor.onError(err, handler);

      final exception = handler.rejected!.error as ServerException;
      expect(exception.code, 'EMAIL_ALREADY_EXISTS');
      expect(exception.message, '이미 사용 중인 이메일입니다.');
      expect(exception.statusCode, 400);
    });

    test('correlation_id 포함 시 ServerException에 전달', () {
      final response = Response<dynamic>(
        requestOptions: _opts(),
        statusCode: 500,
        data: {
          'error': {
            'code': 'INTERNAL_ERROR',
            'message': 'Internal error',
            'correlation_id': 'abc-123',
          },
        },
      );
      final err = _makeDioException(
        type: DioExceptionType.badResponse,
        response: response,
      );
      interceptor.onError(err, handler);

      final exception = handler.rejected!.error as ServerException;
      expect(exception.correlationId, 'abc-123');
    });

    test('code 없는 서버 응답 → code: UNKNOWN', () {
      final response = Response<dynamic>(
        requestOptions: _opts(),
        statusCode: 500,
        data: {
          'error': {'message': 'unexpected'},
        },
      );
      final err = _makeDioException(
        type: DioExceptionType.badResponse,
        response: response,
      );
      interceptor.onError(err, handler);

      final exception = handler.rejected!.error as ServerException;
      expect(exception.code, 'UNKNOWN');
    });
  });

  group('ErrorInterceptor — 변환 불필요한 오류', () {
    test('error 키 없는 응답 → handler.next() 전달', () {
      final response = Response<dynamic>(
        requestOptions: _opts(),
        statusCode: 422,
        data: {'detail': 'Validation error'},
      );
      final err = _makeDioException(
        type: DioExceptionType.badResponse,
        response: response,
      );
      interceptor.onError(err, handler);

      expect(handler.nexted, isNotNull);
      expect(handler.rejected, isNull);
    });

    test('응답 없는 unknown 오류 → handler.next() 전달', () {
      final err = _makeDioException(type: DioExceptionType.unknown);
      interceptor.onError(err, handler);

      expect(handler.nexted, isNotNull);
      expect(handler.rejected, isNull);
    });
  });
}
