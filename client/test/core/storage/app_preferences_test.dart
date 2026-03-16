import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:coin_trader/core/storage/app_preferences.dart';

void main() {
  late AppPreferences prefs;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final sp = await SharedPreferences.getInstance();
    prefs = AppPreferences(sp);
  });

  group('AppPreferences — ThemeMode', () {
    test('기본값: ThemeMode.system', () {
      expect(prefs.getThemeMode(), ThemeMode.system);
    });

    test('setThemeMode(dark) → getThemeMode() == dark', () async {
      await prefs.setThemeMode(ThemeMode.dark);
      expect(prefs.getThemeMode(), ThemeMode.dark);
    });

    test('setThemeMode(light) → getThemeMode() == light', () async {
      await prefs.setThemeMode(ThemeMode.light);
      expect(prefs.getThemeMode(), ThemeMode.light);
    });
  });

  group('AppPreferences — Locale', () {
    test('기본값: null (시스템 로케일 사용)', () {
      expect(prefs.getLocale(), isNull);
    });

    test('setLocale("ko") → getLocale() == "ko"', () async {
      await prefs.setLocale('ko');
      expect(prefs.getLocale(), 'ko');
    });

    test('setLocale("en") → getLocale() == "en"', () async {
      await prefs.setLocale('en');
      expect(prefs.getLocale(), 'en');
    });
  });

  group('AppPreferences — PriceColorScheme', () {
    test('기본값: "korean"', () {
      expect(prefs.getPriceColorScheme(), 'korean');
    });

    test('setPriceColorScheme("global") → getPriceColorScheme() == "global"',
        () async {
      await prefs.setPriceColorScheme('global');
      expect(prefs.getPriceColorScheme(), 'global');
    });
  });

  group('AppPreferences — PushEnabled', () {
    test('기본값: true', () {
      expect(prefs.getPushEnabled(), isTrue);
    });

    test('setPushEnabled(false) → getPushEnabled() == false', () async {
      await prefs.setPushEnabled(false);
      expect(prefs.getPushEnabled(), isFalse);
    });
  });

  group('AppPreferences — LastSelectedExchange', () {
    test('기본값: null', () {
      expect(prefs.getLastSelectedExchange(), isNull);
    });

    test('setLastSelectedExchange("upbit") → getLastSelectedExchange() == "upbit"',
        () async {
      await prefs.setLastSelectedExchange('upbit');
      expect(prefs.getLastSelectedExchange(), 'upbit');
    });
  });

  group('AppPreferences — clearAll', () {
    test('clearAll 후 모든 값이 기본값으로 초기화됨', () async {
      await prefs.setThemeMode(ThemeMode.dark);
      await prefs.setLocale('en');
      await prefs.setPriceColorScheme('global');
      await prefs.setPushEnabled(false);

      await prefs.clearAll();

      expect(prefs.getThemeMode(), ThemeMode.system);
      expect(prefs.getLocale(), isNull);
      expect(prefs.getPriceColorScheme(), 'korean');
      expect(prefs.getPushEnabled(), isTrue);
    });
  });
}
