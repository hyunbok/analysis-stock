import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// JWT 토큰 등 민감 데이터를 OS Keychain/Keystore에 저장하는 래퍼.
class SecureStorage {
  final FlutterSecureStorage _storage;

  static const _kAccessToken = 'ct_access_token';
  static const _kRefreshToken = 'ct_refresh_token';

  const SecureStorage(this._storage);

  // ── 토큰 전용 API ──────────────────────────────────────────

  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    await Future.wait([
      _storage.write(key: _kAccessToken, value: accessToken),
      _storage.write(key: _kRefreshToken, value: refreshToken),
    ]);
  }

  Future<String?> readAccessToken() => _storage.read(key: _kAccessToken);

  Future<String?> readRefreshToken() => _storage.read(key: _kRefreshToken);

  Future<void> clearTokens() async {
    await Future.wait([
      _storage.delete(key: _kAccessToken),
      _storage.delete(key: _kRefreshToken),
    ]);
  }

  // ── 범용 API ──────────────────────────────────────────────

  Future<void> write({required String key, required String value}) =>
      _storage.write(key: key, value: value);

  Future<String?> read({required String key}) => _storage.read(key: key);

  Future<void> delete({required String key}) => _storage.delete(key: key);
}
