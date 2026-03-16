import 'package:dio/dio.dart';

import '../../storage/secure_storage.dart';

/// 모든 요청에 `Authorization: Bearer {access_token}` 헤더를 주입한다.
///
/// 인증이 불필요한 경로([_skipPaths])는 skip한다.
class AuthInterceptor extends Interceptor {
  final SecureStorage _storage;

  static const _skipPaths = [
    '/api/v1/auth/login',
    '/api/v1/auth/register',
    '/api/v1/auth/refresh',
    '/api/v1/auth/forgot-password',
    '/api/v1/auth/reset-password',
    '/api/v1/auth/social/',
  ];

  AuthInterceptor(this._storage);

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    final shouldSkip = _skipPaths.any((p) => options.path.contains(p));
    if (!shouldSkip) {
      final token = await _storage.readAccessToken();
      if (token != null) {
        options.headers['Authorization'] = 'Bearer $token';
      }
    }
    handler.next(options);
  }
}
