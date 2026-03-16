import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../../constants/constants.dart';
import '../../storage/secure_storage.dart';

/// 401 응답 시 refresh token으로 토큰을 갱신하고 원래 요청을 재시도한다.
///
/// - [Completer] lock으로 동시 갱신 요청 방지
/// - 갱신 실패 시 [onUnauthorized] 콜백 호출 (→ authState 초기화 → /login)
/// - `/auth/refresh` 경로는 재시도 대상에서 제외
class RefreshInterceptor extends Interceptor {
  final SecureStorage _storage;
  final VoidCallback onUnauthorized;

  /// 인터셉터 없는 전용 Dio (순환 호출 방지)
  final Dio _refreshDio;

  Completer<void>? _lock;

  RefreshInterceptor({
    required SecureStorage storage,
    required this.onUnauthorized,
    Dio? refreshDio,
  })  : _storage = storage,
        _refreshDio = refreshDio ??
            Dio(BaseOptions(baseUrl: AppConstants.apiBaseUrl));

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode != 401) {
      return handler.next(err);
    }
    // refresh 요청 자체가 401이면 재시도 없이 전파
    if (err.requestOptions.path.contains('/auth/refresh')) {
      return handler.next(err);
    }

    // 이미 갱신 중이면 완료 대기 후 재시도
    if (_lock != null) {
      try {
        await _lock!.future;
        final response = await _retry(err.requestOptions);
        return handler.resolve(response);
      } catch (_) {
        return handler.next(err);
      }
    }

    _lock = Completer();
    try {
      final refreshToken = await _storage.readRefreshToken();
      if (refreshToken == null) throw StateError('no_refresh_token');

      final res = await _refreshDio.post<Map<String, dynamic>>(
        '/api/v1/auth/refresh',
        data: {'refresh_token': refreshToken},
      );

      // Refresh Token Rotation: 새 access + refresh 모두 저장
      final data = res.data!['data'] as Map<String, dynamic>;
      await _storage.saveTokens(
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
      );

      _lock!.complete();
      _lock = null;

      final response = await _retry(err.requestOptions);
      handler.resolve(response);
    } catch (e) {
      _lock?.completeError(e);
      _lock = null;
      await _storage.clearTokens();
      onUnauthorized();
      handler.next(err);
    }
  }

  Future<Response<dynamic>> _retry(RequestOptions options) async {
    final newToken = await _storage.readAccessToken();
    final headers = Map<String, dynamic>.from(options.headers);
    if (newToken != null) {
      headers['Authorization'] = 'Bearer $newToken';
    }
    return _refreshDio.fetch<dynamic>(
      options.copyWith(headers: headers),
    );
  }
}
