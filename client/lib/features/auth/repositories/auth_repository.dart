import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/models/api_response.dart';
import '../../../core/providers/dio_provider.dart';
import '../models/auth_tokens.dart';
import '../models/social_login_request.dart';
import '../models/user.dart';

part 'auth_repository.g.dart';

@riverpod
AuthRepository authRepository(AuthRepositoryRef ref) {
  return AuthRepository(ref.watch(dioClientProvider));
}

class AuthRepository {
  final Dio _dio;

  const AuthRepository(this._dio);

  Future<AuthTokens> register({
    required String email,
    required String password,
    required String nickname,
  }) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/api/v1/auth/register',
      data: {'email': email, 'password': password, 'nickname': nickname},
    );
    return AuthTokens.fromJson(
      ApiResponse<Map<String, dynamic>>.fromJson(
        res.data!,
        (json) => json as Map<String, dynamic>,
      ).data!,
    );
  }

  Future<AuthTokens> login({
    required String email,
    required String password,
  }) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/api/v1/auth/login',
      data: {'email': email, 'password': password},
    );
    return AuthTokens.fromJson(
      ApiResponse<Map<String, dynamic>>.fromJson(
        res.data!,
        (json) => json as Map<String, dynamic>,
      ).data!,
    );
  }

  Future<void> logout() async {
    await _dio.post<void>('/api/v1/auth/logout');
  }

  Future<User> getMe() async {
    final res = await _dio.get<Map<String, dynamic>>('/api/v1/users/me');
    return User.fromJson(
      ApiResponse<Map<String, dynamic>>.fromJson(
        res.data!,
        (json) => json as Map<String, dynamic>,
      ).data!,
    );
  }

  Future<User> updateMe({String? nickname}) async {
    final res = await _dio.put<Map<String, dynamic>>(
      '/api/v1/users/me',
      data: {if (nickname != null) 'nickname': nickname},
    );
    return User.fromJson(
      ApiResponse<Map<String, dynamic>>.fromJson(
        res.data!,
        (json) => json as Map<String, dynamic>,
      ).data!,
    );
  }

  Future<void> deleteAccount({required String refreshToken}) async {
    await _dio.delete<void>(
      '/api/v1/users/me',
      data: {'refresh_token': refreshToken},
    );
  }

  Future<AuthTokens> socialLogin(SocialLoginRequest request) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/api/v1/auth/social/${request.provider}',
      data: {'id_token': request.idToken},
    );
    return AuthTokens.fromJson(
      ApiResponse<Map<String, dynamic>>.fromJson(
        res.data!,
        (json) => json as Map<String, dynamic>,
      ).data!,
    );
  }

  Future<void> forgotPassword(String email) async {
    await _dio.post<void>(
      '/api/v1/auth/forgot-password',
      data: {'email': email},
    );
  }

  Future<void> resetPassword({
    required String token,
    required String newPassword,
  }) async {
    await _dio.post<void>(
      '/api/v1/auth/reset-password',
      data: {'token': token, 'new_password': newPassword},
    );
  }
}
