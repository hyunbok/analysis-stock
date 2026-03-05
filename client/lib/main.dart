import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

void main() {
  runApp(const ProviderScope(child: CoinTraderApp()));
}

class CoinTraderApp extends StatelessWidget {
  const CoinTraderApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CoinTrader',
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF1261C4),
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        colorSchemeSeed: const Color(0xFF42A5F5),
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0D0D1A),
      ),
      themeMode: ThemeMode.system,
      home: const Scaffold(
        body: Center(child: Text('CoinTrader')),
      ),
    );
  }
}
