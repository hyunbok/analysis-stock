import 'package:flutter/material.dart';

/// 앱 전역 색상 상수.
///
/// TradingColors ThemeExtension으로 커버되지 않는 기능별 색상을 정의한다.
abstract final class AppColors {
  // AI 자동매매 색상
  static const aiOn = Color(0xFF00BCD4);
  static const aiAnalyzing = Color(0xFF29B6F6);
  static const aiOff = Color(0xFF9E9E9E);

  // P&L 색상
  static const profit = Color(0xFF26A69A);
  static const loss = Color(0xFFEF5350);
  static const neutral = Color(0xFF9E9E9E);
}
