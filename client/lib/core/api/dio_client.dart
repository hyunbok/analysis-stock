import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../constants/constants.dart';
import '../storage/secure_storage.dart';
import 'interceptors/auth_interceptor.dart';
import 'interceptors/error_interceptor.dart';
import 'interceptors/refresh_interceptor.dart';

/// [Dio] 인스턴스를 생성하는 팩토리 함수.
///
/// 인터셉터 체인 순서:
/// 1. [LogInterceptor]      — kDebugMode에서만 활성화
/// 2. [AuthInterceptor]     — Bearer 토큰 주입
/// 3. [RefreshInterceptor]  — 401 → 토큰 갱신 → 재시도
/// 4. [ErrorInterceptor]    — 에러 응답 → ApiException 변환
///
/// 환경 오버라이드: `flutter run --dart-define=API_BASE_URL=http://localhost:8000`
Dio buildDio(SecureStorage storage, {required void Function() onUnauthorized}) {
  final dio = Dio(
    BaseOptions(
      baseUrl: AppConstants.apiBaseUrl,
      connectTimeout: AppConstants.connectTimeout,
      receiveTimeout: AppConstants.receiveTimeout,
      headers: {'Content-Type': 'application/json'},
    ),
  );

  dio.interceptors.addAll([
    if (kDebugMode)
      LogInterceptor(
        requestBody: true,
        responseBody: true,
        logPrint: (o) => debugPrint(o.toString()),
      ),
    AuthInterceptor(storage),
    RefreshInterceptor(storage: storage, onUnauthorized: onUnauthorized),
    ErrorInterceptor(),
  ]);

  return dio;
}
