import 'package:flutter/material.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/storage_provider.dart';
import '../models/app_settings.dart';

part 'settings_provider.g.dart';

/// 앱 설정 상태 관리.
///
/// AppPreferences에서 초기값을 읽어 상태를 초기화한다.
@Riverpod(keepAlive: true)
class SettingsNotifier extends _$SettingsNotifier {
  @override
  AppSettings build() {
    final prefs = ref.watch(appPreferencesProvider);
    return AppSettings(
      themeMode: prefs.getThemeMode(),
      locale: prefs.getLocale() ?? 'ko',
      priceColorScheme: prefs.getPriceColorScheme(),
      pushEnabled: prefs.getPushEnabled(),
    );
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    await ref.read(appPreferencesProvider).setThemeMode(mode);
    state = state.copyWith(themeMode: mode);
  }

  Future<void> setLocale(String locale) async {
    await ref.read(appPreferencesProvider).setLocale(locale);
    state = state.copyWith(locale: locale);
  }

  Future<void> setPriceColorScheme(String scheme) async {
    await ref.read(appPreferencesProvider).setPriceColorScheme(scheme);
    state = state.copyWith(priceColorScheme: scheme);
  }

  Future<void> setPushEnabled(bool enabled) async {
    await ref.read(appPreferencesProvider).setPushEnabled(enabled);
    state = state.copyWith(pushEnabled: enabled);
  }
}

/// 현재 테마 모드 (파생 프로바이더).
@Riverpod(keepAlive: true)
ThemeMode themeMode(ThemeModeRef ref) {
  return ref.watch(settingsNotifierProvider).themeMode;
}

/// 현재 로케일 (파생 프로바이더).
@Riverpod(keepAlive: true)
Locale locale(LocaleRef ref) {
  final code = ref.watch(settingsNotifierProvider).locale;
  return Locale(code);
}

/// 가격 색상 모드 (파생 프로바이더).
@Riverpod(keepAlive: true)
String priceColorScheme(PriceColorSchemeRef ref) {
  return ref.watch(settingsNotifierProvider).priceColorScheme;
}
