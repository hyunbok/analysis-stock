import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coin_trader/core/api/interceptors/refresh_interceptor.dart';
import 'package:coin_trader/core/storage/secure_storage.dart';

/// 인메모리 SecureStorage Fake.
class _FakeSecureStorage implements SecureStorage {
  String? _accessToken;
  String? _refreshToken;

  _FakeSecureStorage({String? accessToken, String? refreshToken})
      : _accessToken = accessToken,
        _refreshToken = refreshToken;

  @override
  Future<String?> readAccessToken() async => _accessToken;

  @override
  Future<String?> readRefreshToken() async => _refreshToken;

  @override
  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    _accessToken = accessToken;
    _refreshToken = refreshToken;
  }

  @override
  Future<void> clearTokens() async {
    _accessToken = null;
    _refreshToken = null;
  }

  @override
  Future<void> write({required String key, required String value}) async {}

  @override
  Future<String?> read({required String key}) async => null;

  @override
  Future<void> delete({required String key}) async {}
}

/// ErrorInterceptorHandler를 캡처하는 Fake.
class _CaptureErrorHandler extends ErrorInterceptorHandler {
  Response<dynamic>? resolved;
  DioException? nexted;
  DioException? rejected;

  @override
  void resolve(Response<dynamic> response,
      {bool callFollowingResponseInterceptor = false}) {
    resolved = response;
  }

  @override
  void next(DioException err) {
    nexted = err;
  }

  @override
  void reject(DioException err, {bool callFollowingErrorInterceptor = false}) {
    rejected = err;
  }
}

/// 단순 HTTP mock — 미리 설정된 응답 반환.
class _MockHttpAdapter implements HttpClientAdapter {
  final Map<String, dynamic>? Function(RequestOptions) _responder;

  _MockHttpAdapter(this._responder);

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final data = _responder(options);
    if (data == null) {
      throw DioException(
        requestOptions: options,
        response: Response<dynamic>(
          requestOptions: options,
          statusCode: 500,
        ),
        type: DioExceptionType.badResponse,
      );
    }
    return ResponseBody.fromString(
      '{"data": $data}',
      200,
      headers: {
        'content-type': ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

DioException _make401(RequestOptions opts) => DioException(
      requestOptions: opts,
      response: Response<dynamic>(
        requestOptions: opts,
        statusCode: 401,
        data: {'error': 'unauthorized'},
      ),
      type: DioExceptionType.badResponse,
    );

void main() {
  group('RefreshInterceptor', () {
    test('401 아닌 오류 → handler.next()로 그냥 전달', () async {
      final storage = _FakeSecureStorage();
      bool unauthorizedCalled = false;
      final interceptor = RefreshInterceptor(
        storage: storage,
        onUnauthorized: () => unauthorizedCalled = true,
      );
      final handler = _CaptureErrorHandler();

      final err = DioException(
        requestOptions: RequestOptions(path: '/api/v1/coins'),
        type: DioExceptionType.connectionError,
      );
      await interceptor.onError(err, handler);

      expect(handler.nexted, isNotNull);
      expect(unauthorizedCalled, isFalse);
    });

    test('/auth/refresh 자체 401 → 재시도 없이 next()로 전달', () async {
      final storage = _FakeSecureStorage(refreshToken: 'rt');
      bool unauthorizedCalled = false;
      final interceptor = RefreshInterceptor(
        storage: storage,
        onUnauthorized: () => unauthorizedCalled = true,
      );
      final handler = _CaptureErrorHandler();

      final opts = RequestOptions(path: '/api/v1/auth/refresh');
      await interceptor.onError(_make401(opts), handler);

      expect(handler.nexted, isNotNull);
      expect(unauthorizedCalled, isFalse);
    });

    test('refresh token 없을 때 401 → clearTokens + onUnauthorized', () async {
      final storage = _FakeSecureStorage(); // no refresh token
      bool unauthorizedCalled = false;
      final interceptor = RefreshInterceptor(
        storage: storage,
        onUnauthorized: () => unauthorizedCalled = true,
        refreshDio: Dio(BaseOptions(baseUrl: 'http://test')),
      );
      final handler = _CaptureErrorHandler();

      final opts = RequestOptions(path: '/api/v1/coins');
      await interceptor.onError(_make401(opts), handler);

      expect(unauthorizedCalled, isTrue);
      expect(await storage.readAccessToken(), isNull);
      expect(await storage.readRefreshToken(), isNull);
      expect(handler.nexted, isNotNull);
    });

    test('refresh 성공 → 새 토큰 저장', () async {
      final storage = _FakeSecureStorage(
        accessToken: 'old-at',
        refreshToken: 'old-rt',
      );
      bool unauthorizedCalled = false;

      final refreshDio = Dio(BaseOptions(baseUrl: 'http://test'));
      refreshDio.httpClientAdapter = _MockHttpAdapter((opts) {
        if (opts.path.contains('/auth/refresh')) {
          return '{"access_token":"new-at","refresh_token":"new-rt","expires_in":1800}';
        }
        return '{}'; // retry response
      });

      final interceptor = RefreshInterceptor(
        storage: storage,
        onUnauthorized: () => unauthorizedCalled = true,
        refreshDio: refreshDio,
      );
      final handler = _CaptureErrorHandler();

      final opts = RequestOptions(
        path: '/api/v1/coins',
        baseUrl: 'http://test',
      );
      await interceptor.onError(_make401(opts), handler);

      expect(unauthorizedCalled, isFalse);
      expect(await storage.readAccessToken(), 'new-at');
      expect(await storage.readRefreshToken(), 'new-rt');
    });

    test('동시 401 요청 — lock으로 중복 갱신 방지', () async {
      final storage = _FakeSecureStorage(
        accessToken: 'old-at',
        refreshToken: 'old-rt',
      );
      int refreshCallCount = 0;

      final refreshDio = Dio(BaseOptions(baseUrl: 'http://test'));
      refreshDio.httpClientAdapter = _MockHttpAdapter((opts) {
        if (opts.path.contains('/auth/refresh')) {
          refreshCallCount++;
          return '{"access_token":"new-at","refresh_token":"new-rt","expires_in":1800}';
        }
        return '{}';
      });

      final interceptor = RefreshInterceptor(
        storage: storage,
        onUnauthorized: () {},
        refreshDio: refreshDio,
      );

      final opts1 = RequestOptions(path: '/api/v1/coins', baseUrl: 'http://test');
      final opts2 = RequestOptions(path: '/api/v1/portfolio', baseUrl: 'http://test');
      final handler1 = _CaptureErrorHandler();
      final handler2 = _CaptureErrorHandler();

      // 두 401 동시 발생
      await Future.wait([
        interceptor.onError(_make401(opts1), handler1),
        interceptor.onError(_make401(opts2), handler2),
      ]);

      // refresh API는 1번만 호출되어야 함
      expect(refreshCallCount, 1);
    });
  });
}
