/// WebSocket 연결 상태.
///
/// PRD §5.2 연결 상태 UI 매핑:
/// - [connected]    → 녹색 인디케이터
/// - [connecting] / [reconnecting] → 황색 + 스피너 + "재연결 중" 배너
/// - [disconnected] → 적색 + "연결 끊김" 배너
enum WsConnectionState { disconnected, connecting, connected, reconnecting }
