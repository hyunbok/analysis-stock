import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 앱 설정 및 비민감 캐시를 SharedPreferences에 저장하는 래퍼.
///
/// SharedPreferences는 동기 read가 가능하므로 getter는 동기로 정의한다.
class AppPreferences {
  final SharedPreferences _prefs;

  static const _kThemeMode = 'theme_mode';
  static const _kLocale = 'locale';
  static const _kPriceColorScheme = 'price_color_scheme';
  static const _kPushEnabled = 'push_enabled';
  static const _kLastExchange = 'last_exchange';

  const AppPreferences(this._prefs);

  // ── 테마 ──────────────────────────────────────────────────

  Future<void> setThemeMode(ThemeMode mode) =>
      _prefs.setString(_kThemeMode, mode.name);

  ThemeMode getThemeMode() {
    final value = _prefs.getString(_kThemeMode);
    return ThemeMode.values.firstWhere(
      (m) => m.name == value,
      orElse: () => ThemeMode.system,
    );
  }

  // ── 로케일 ────────────────────────────────────────────────

  Future<void> setLocale(String localeCode) =>
      _prefs.setString(_kLocale, localeCode);

  /// null 반환 시 시스템 로케일 사용
  String? getLocale() => _prefs.getString(_kLocale);

  // ── 가격 색상 ─────────────────────────────────────────────

  /// scheme: 'korean' | 'global'
  Future<void> setPriceColorScheme(String scheme) =>
      _prefs.setString(_kPriceColorScheme, scheme);

  /// 기본값: 'korean'
  String getPriceColorScheme() =>
      _prefs.getString(_kPriceColorScheme) ?? 'korean';

  // ── 알림 ──────────────────────────────────────────────────

  Future<void> setPushEnabled(bool enabled) =>
      _prefs.setBool(_kPushEnabled, enabled);

  bool getPushEnabled() => _prefs.getBool(_kPushEnabled) ?? true;

  // ── 세션 힌트 (비민감) ────────────────────────────────────

  Future<void> setLastSelectedExchange(String exchange) =>
      _prefs.setString(_kLastExchange, exchange);

  String? getLastSelectedExchange() => _prefs.getString(_kLastExchange);

  // ── 초기화 (로그아웃 시 호출) ────────────────────────────

  Future<void> clearAll() => _prefs.clear();
}
