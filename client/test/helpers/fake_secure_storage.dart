import 'package:coin_trader/core/storage/secure_storage.dart';

/// 테스트 전용 인메모리 SecureStorage.
///
/// FlutterSecureStorage의 플랫폼 채널 의존 없이 단위 테스트 가능.
class FakeSecureStorage implements SecureStorage {
  String? _accessToken;
  String? _refreshToken;
  final Map<String, String> _store = {};

  FakeSecureStorage({String? accessToken, String? refreshToken})
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
  Future<void> write({required String key, required String value}) async {
    _store[key] = value;
  }

  @override
  Future<String?> read({required String key}) async => _store[key];

  @override
  Future<void> delete({required String key}) async {
    _store.remove(key);
  }
}
