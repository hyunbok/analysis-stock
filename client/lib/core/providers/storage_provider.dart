import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../storage/app_preferences.dart';
import '../storage/secure_storage.dart';

part 'storage_provider.g.dart';

/// [SecureStorage] 인스턴스를 제공한다.
///
/// [FlutterSecureStorage]는 동기 생성이므로 override 없이 직접 생성.
/// Android: `encryptedSharedPreferences` 활성화.
@Riverpod(keepAlive: true)
SecureStorage secureStorage(SecureStorageRef ref) {
  return SecureStorage(
    const FlutterSecureStorage(
      aOptions: AndroidOptions(encryptedSharedPreferences: true),
    ),
  );
}

/// [SharedPreferences] 인스턴스를 제공한다.
///
/// **main.dart에서 반드시 override 필요**:
/// ```dart
/// final prefs = await SharedPreferences.getInstance();
/// ProviderScope(
///   overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
///   ...
/// )
/// ```
@Riverpod(keepAlive: true)
SharedPreferences sharedPreferences(SharedPreferencesRef ref) {
  throw StateError(
    'sharedPreferencesProvider must be overridden in ProviderScope. '
    'Initialize with SharedPreferences.getInstance() in main().',
  );
}

/// [AppPreferences] 인스턴스를 제공한다.
@Riverpod(keepAlive: true)
AppPreferences appPreferences(AppPreferencesRef ref) {
  return AppPreferences(ref.watch(sharedPreferencesProvider));
}
