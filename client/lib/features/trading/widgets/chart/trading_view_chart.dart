import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// TradingView Lightweight Charts WebView 래퍼.
class TradingViewChart extends StatefulWidget {
  final String exchange;
  final String market;
  final String interval;
  final bool isDark;
  final ValueChanged<String>? onIntervalChanged;

  const TradingViewChart({
    super.key,
    required this.exchange,
    required this.market,
    this.interval = '1m',
    this.isDark = true,
    this.onIntervalChanged,
  });

  @override
  State<TradingViewChart> createState() => _TradingViewChartState();
}

class _TradingViewChartState extends State<TradingViewChart> {
  late WebViewController _controller;
  bool _isReady = false;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel(
        'FlutterBridge',
        onMessageReceived: _onBridgeMessage,
      )
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageFinished: (_) => _initChart(),
        ),
      )
      ..loadFlutterAsset('assets/html/tradingview.html');
  }

  @override
  void didUpdateWidget(TradingViewChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_isReady) return;
    if (oldWidget.isDark != widget.isDark) {
      _controller.runJavaScript(
        'setTheme(${widget.isDark});',
      );
    }
    if (oldWidget.interval != widget.interval) {
      _controller.runJavaScript(
        "setInterval('${widget.interval}');",
      );
    }
  }

  void _initChart() {
    _controller.runJavaScript(
      'initChart(${jsonEncode({
        'isDark': widget.isDark,
        'symbol': '${widget.exchange}:${widget.market}',
        'interval': widget.interval,
      })});',
    );
    setState(() => _isReady = true);
  }

  void _onBridgeMessage(JavaScriptMessage message) {
    try {
      final data = jsonDecode(message.message) as Map<String, dynamic>;
      final type = data['type'] as String?;
      if (type == 'intervalChanged') {
        widget.onIntervalChanged?.call(data['interval'] as String);
      }
    } catch (_) {}
  }

  void setData(List<Map<String, dynamic>> candles) {
    if (!_isReady) return;
    _controller.runJavaScript(
      'setData(${jsonEncode(candles)});',
    );
  }

  void updateCandle(Map<String, dynamic> candle) {
    if (!_isReady) return;
    _controller.runJavaScript(
      'updateCandle(${jsonEncode(candle)});',
    );
  }

  @override
  Widget build(BuildContext context) {
    return WebViewWidget(controller: _controller);
  }
}
