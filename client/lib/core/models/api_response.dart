import 'package:freezed_annotation/freezed_annotation.dart';

part 'api_response.freezed.dart';
part 'api_response.g.dart';

/// 서버 공통 응답 래퍼.
///
/// 성공: `{ "data": T, "error": null, "meta": { "timestamp": "..." } }`
/// 실패: `{ "data": null, "error": { "code": "...", "message": "..." }, "meta": {...} }`
@Freezed(genericArgumentFactories: true)
class ApiResponse<T> with _$ApiResponse<T> {
  const factory ApiResponse({
    T? data,
    ApiError? error,
    ApiMeta? meta,
  }) = _ApiResponse<T>;

  factory ApiResponse.fromJson(
    Map<String, dynamic> json,
    T Function(Object?) fromJsonT,
  ) =>
      _$ApiResponseFromJson(json, fromJsonT);
}

@freezed
class ApiError with _$ApiError {
  const factory ApiError({
    required String code,
    required String message,
    Map<String, dynamic>? details,
    @JsonKey(name: 'correlation_id') String? correlationId,
  }) = _ApiError;

  factory ApiError.fromJson(Map<String, dynamic> json) =>
      _$ApiErrorFromJson(json);
}

@freezed
class ApiMeta with _$ApiMeta {
  const factory ApiMeta({
    required String timestamp,
  }) = _ApiMeta;

  factory ApiMeta.fromJson(Map<String, dynamic> json) =>
      _$ApiMetaFromJson(json);
}
