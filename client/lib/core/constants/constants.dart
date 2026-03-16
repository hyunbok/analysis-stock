abstract final class AppConstants {
  /// API 베이스 URL.
  /// 오버라이드: flutter run --dart-define=API_BASE_URL=http://localhost:8000
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://api.cointrader.example.com',
  );

  /// WebSocket URL.
  /// 오버라이드: flutter run --dart-define=WS_URL=ws://localhost:8000/ws/v1
  static const wsUrl = String.fromEnvironment(
    'WS_URL',
    defaultValue: 'wss://api.cointrader.example.com/ws/v1',
  );

  // HTTP 타임아웃
  static const connectTimeout = Duration(seconds: 10);
  static const receiveTimeout = Duration(seconds: 30);

  // WebSocket 설정
  static const wsHeartbeatInterval = Duration(seconds: 30);
  static const wsPongTimeout = Duration(seconds: 10);
  static const wsMaxRetryDelaySec = 30;
}
