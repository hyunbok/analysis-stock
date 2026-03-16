import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/settings/providers/settings_provider.dart';
import '../l10n/app_localizations.dart';
import 'router.dart';
import 'theme.dart';

/// 앱 루트 위젯.
///
/// - GoRouter: routerProvider
/// - 테마: themeModeProvider + priceColorSchemeProvider
/// - i18n: AppLocalizations (5개 언어)
/// - 인증 상태 리스너: authStateProvider (GoRouter redirect 연동)
class CoinTraderApp extends ConsumerWidget {
  const CoinTraderApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final themeMode = ref.watch(themeModeProvider);
    final priceColorScheme = ref.watch(priceColorSchemeProvider);
    final locale = ref.watch(localeProvider);

    final isKorean = priceColorScheme == 'korean';

    return MaterialApp.router(
      title: 'CoinTrader',
      theme: isKorean ? AppTheme.light : AppTheme.lightWith(TradingColors.global),
      darkTheme: isKorean ? AppTheme.dark : AppTheme.darkWith(TradingColors.globalDark),
      themeMode: themeMode,
      routerConfig: router,
      locale: locale,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
    );
  }
}
