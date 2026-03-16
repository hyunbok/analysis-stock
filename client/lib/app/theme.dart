import 'package:flutter/material.dart';

/// 한국식/글로벌 가격 색상 모드.
///
/// - [korean]: 빨강=상승(매수), 파랑=하락(매도) — 업비트, 코인원 관행
/// - [global]: 초록=상승(매수), 빨강=하락(매도) — Binance, Coinbase 관행
enum PriceColorMode { korean, global }

/// 트레이딩 전용 색상 ThemeExtension.
///
/// 사용법:
/// ```dart
/// final colors = Theme.of(context).extension<TradingColors>()!;
/// Text('매수', style: TextStyle(color: colors.buyColor));
/// ```
class TradingColors extends ThemeExtension<TradingColors> {
  final Color buyColor;
  final Color sellColor;
  final Color holdColor;

  const TradingColors({
    required this.buyColor,
    required this.sellColor,
    required this.holdColor,
  });

  /// 한국식 Light: 빨강=상승, 파랑=하락
  static const korean = TradingColors(
    buyColor: Color(0xFFD24F45),
    sellColor: Color(0xFF1261C4),
    holdColor: Color(0xFF9E9E9E),
  );

  /// 한국식 Dark
  static const koreanDark = TradingColors(
    buyColor: Color(0xFFEF5350),
    sellColor: Color(0xFF42A5F5),
    holdColor: Color(0xFF9E9E9E),
  );

  /// 글로벌 Light: 초록=상승, 빨강=하락
  static const global = TradingColors(
    buyColor: Color(0xFF4CAF50),
    sellColor: Color(0xFFD24F45),
    holdColor: Color(0xFF9E9E9E),
  );

  /// 글로벌 Dark
  static const globalDark = TradingColors(
    buyColor: Color(0xFF66BB6A),
    sellColor: Color(0xFFEF5350),
    holdColor: Color(0xFF9E9E9E),
  );

  @override
  TradingColors copyWith({Color? buyColor, Color? sellColor, Color? holdColor}) {
    return TradingColors(
      buyColor: buyColor ?? this.buyColor,
      sellColor: sellColor ?? this.sellColor,
      holdColor: holdColor ?? this.holdColor,
    );
  }

  @override
  TradingColors lerp(covariant TradingColors? other, double t) {
    if (other == null) return this;
    return TradingColors(
      buyColor: Color.lerp(buyColor, other.buyColor, t)!,
      sellColor: Color.lerp(sellColor, other.sellColor, t)!,
      holdColor: Color.lerp(holdColor, other.holdColor, t)!,
    );
  }
}

/// 앱 전역 테마 설정.
///
/// Material 3 기반, TradingColors ThemeExtension 포함.
/// Pretendard 폰트: pubspec.yaml에 폰트 파일 추가 후 fontFamily 주석 해제.
class AppTheme {
  AppTheme._();

  static const _seedColorLight = Color(0xFF1261C4);
  static const _seedColorDark = Color(0xFF42A5F5);
  static const _darkBackground = Color(0xFF0D0D1A);

  static ThemeData get light => ThemeData(
        colorSchemeSeed: _seedColorLight,
        useMaterial3: true,
        // fontFamily: 'Pretendard', // TODO: Enable after adding font files
        extensions: const [TradingColors.korean],
      );

  static ThemeData get dark => ThemeData(
        colorSchemeSeed: _seedColorDark,
        useMaterial3: true,
        brightness: Brightness.dark,
        // fontFamily: 'Pretendard', // TODO: Enable after adding font files
        scaffoldBackgroundColor: _darkBackground,
        extensions: const [TradingColors.koreanDark],
      );

  /// 가격 색상 모드에 따라 Light 테마 반환.
  static ThemeData lightWith(TradingColors colors) =>
      light.copyWith(extensions: [colors]);

  /// 가격 색상 모드에 따라 Dark 테마 반환.
  static ThemeData darkWith(TradingColors colors) =>
      dark.copyWith(extensions: [colors]);
}
