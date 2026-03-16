import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:coin_trader/core/providers/storage_provider.dart';
import 'package:coin_trader/core/storage/app_preferences.dart';

import 'fake_secure_storage.dart';

export 'fake_secure_storage.dart';

/// ProviderContainer를 테스트용 override와 함께 생성한다.
///
/// 사용 예:
/// ```dart
/// final container = await makeTestContainer(accessToken: 'my-token');
/// addTearDown(container.dispose);
/// ```
///
/// [accessToken]: 초기 access token (null이면 미인증 상태)
/// [refreshToken]: 초기 refresh token
/// [extraOverrides]: 추가 provider override 목록
Future<ProviderContainer> makeTestContainer({
  String? accessToken,
  String? refreshToken,
  List<Override> extraOverrides = const [],
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final storage = FakeSecureStorage(
    accessToken: accessToken,
    refreshToken: refreshToken,
  );

  return ProviderContainer(
    overrides: [
      secureStorageProvider.overrideWithValue(storage),
      sharedPreferencesProvider.overrideWithValue(prefs),
      appPreferencesProvider.overrideWithValue(AppPreferences(prefs)),
      ...extraOverrides,
    ],
  );
}
