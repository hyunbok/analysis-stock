import 'package:flutter/material.dart';
import 'package:freezed_annotation/freezed_annotation.dart';

part 'app_settings.freezed.dart';

// ThemeMode를 JSON 직렬화하기 위한 헬퍼
class _ThemeModeConverter implements JsonConverter<ThemeMode, String> {
  const _ThemeModeConverter();

  @override
  ThemeMode fromJson(String json) =>
      ThemeMode.values.firstWhere((m) => m.name == json,
          orElse: () => ThemeMode.system);

  @override
  String toJson(ThemeMode mode) => mode.name;
}

@freezed
class AppSettings with _$AppSettings {
  const factory AppSettings({
    @_ThemeModeConverter() @Default(ThemeMode.system) ThemeMode themeMode,
    @Default('ko') String locale,
    @Default('korean') String priceColorScheme, // 'korean' | 'global'
    @Default(true) bool pushEnabled,
    @Default(true) bool priceNotifEnabled,
    @Default(true) bool aiNotifEnabled,
    @Default(true) bool tradeNotifEnabled,
  }) = _AppSettings;
}
