import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coin_trader/core/api/interceptors/auth_interceptor.dart';
import 'package:coin_trader/core/storage/secure_storage.dart';

/// 인메모리 SecureStorage Fake.
class _FakeSecureStorage implements SecureStorage {
  final Map<String, String> _data = {};

  _FakeSecureStorage({String? accessToken}) {
    if (accessToken != null) _data['ct_access_token'] = accessToken;
  }

  @override
  Future<String?> readAccessToken() async => _data['ct_access_token'];

  @override
  Future<String?> readRefreshToken() async => _data['ct_refresh_token'];

  @override
  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    _data['ct_access_token'] = accessToken;
    _data['ct_refresh_token'] = refreshToken;
  }

  @override
  Future<void> clearTokens() async {
    _data.remove('ct_access_token');
    _data.remove('ct_refresh_token');
  }

  @override
  Future<void> write({required String key, required String value}) async {
    _data[key] = value;
  }

  @override
  Future<String?> read({required String key}) async => _data[key];

  @override
  Future<void> delete({required String key}) async {
    _data.remove(key);
  }
}

/// RequestOptions를 캡처하고 항상 next()를 호출하는 핸들러.
class _CaptureRequestHandler extends RequestInterceptorHandler {
  RequestOptions? captured;

  @override
  void next(RequestOptions options) {
    captured = options;
  }
}

void main() {
  group('AuthInterceptor — Bearer 토큰 주입', () {
    test('access token이 있으면 Authorization 헤더 추가', () async {
      final storage = _FakeSecureStorage(accessToken: 'my-token-123');
      final interceptor = AuthInterceptor(storage);
      final handler = _CaptureRequestHandler();

      final options = RequestOptions(path: '/api/v1/coins');
      await interceptor.onRequest(options, handler);

      expect(
        handler.captured?.headers['Authorization'],
        'Bearer my-token-123',
      );
    });

    test('access token이 없으면 Authorization 헤더 미추가', () async {
      final storage = _FakeSecureStorage(); // no token
      final interceptor = AuthInterceptor(storage);
      final handler = _CaptureRequestHandler();

      final options = RequestOptions(path: '/api/v1/coins');
      await interceptor.onRequest(options, handler);

      expect(handler.captured?.headers['Authorization'], isNull);
    });
  });

  group('AuthInterceptor — Skip 경로', () {
    late _FakeSecureStorage storage;
    late AuthInterceptor interceptor;

    setUp(() {
      storage = _FakeSecureStorage(accessToken: 'token');
      interceptor = AuthInterceptor(storage);
    });

    Future<RequestOptions?> _call(String path) async {
      final handler = _CaptureRequestHandler();
      await interceptor.onRequest(RequestOptions(path: path), handler);
      return handler.captured;
    }

    test('/api/v1/auth/login → 토큰 미주입', () async {
      final opts = await _call('/api/v1/auth/login');
      expect(opts?.headers['Authorization'], isNull);
    });

    test('/api/v1/auth/register → 토큰 미주입', () async {
      final opts = await _call('/api/v1/auth/register');
      expect(opts?.headers['Authorization'], isNull);
    });

    test('/api/v1/auth/refresh → 토큰 미주입', () async {
      final opts = await _call('/api/v1/auth/refresh');
      expect(opts?.headers['Authorization'], isNull);
    });

    test('/api/v1/auth/forgot-password → 토큰 미주입', () async {
      final opts = await _call('/api/v1/auth/forgot-password');
      expect(opts?.headers['Authorization'], isNull);
    });

    test('/api/v1/auth/social/google → 토큰 미주입', () async {
      final opts = await _call('/api/v1/auth/social/google');
      expect(opts?.headers['Authorization'], isNull);
    });

    test('/api/v1/portfolio → 토큰 주입', () async {
      final opts = await _call('/api/v1/portfolio');
      expect(opts?.headers['Authorization'], 'Bearer token');
    });
  });
}
