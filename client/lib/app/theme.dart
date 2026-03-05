import 'package:flutter/material.dart';

// Trading color tokens (Korean exchange convention)
// Buy (상승/매수): Light #D24F45 Red, Dark #EF5350
// Sell (하락/매도): Light #1261C4 Blue, Dark #42A5F5
// TODO: Implement TradingColors ThemeExtension in ST7+

class AppTheme {
  AppTheme._();

  static const _seedColorLight = Color(0xFF1261C4);
  static const _seedColorDark = Color(0xFF42A5F5);
  static const _darkBackground = Color(0xFF0D0D1A);

  static ThemeData get light => ThemeData(
        colorSchemeSeed: _seedColorLight,
        useMaterial3: true,
        fontFamily: 'Pretendard',
      );

  static ThemeData get dark => ThemeData(
        colorSchemeSeed: _seedColorDark,
        useMaterial3: true,
        brightness: Brightness.dark,
        fontFamily: 'Pretendard',
        scaffoldBackgroundColor: _darkBackground,
      );
}
