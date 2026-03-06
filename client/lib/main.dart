import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/theme.dart';

void main() {
  runApp(const ProviderScope(child: CoinTraderApp()));
}

class CoinTraderApp extends StatelessWidget {
  const CoinTraderApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CoinTrader',
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.system,
      home: const Scaffold(
        body: Center(child: Text('CoinTrader')),
      ),
    );
  }
}
