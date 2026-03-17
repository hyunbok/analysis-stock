import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'market_state_provider.g.dart';

/// 선택된 거래소 — 홈 탭과 트레이딩 탭 간 공유 상태.
@Riverpod(keepAlive: true)
class SelectedExchange extends _$SelectedExchange {
  @override
  String build() => 'upbit';

  void select(String exchange) => state = exchange;
}

/// 선택된 마켓 — 홈 탭에서 코인 탭 후 트레이딩 탭으로 이동 시 유지.
@Riverpod(keepAlive: true)
class SelectedMarket extends _$SelectedMarket {
  @override
  String build() => 'KRW-BTC';

  void select(String market) => state = market;
}
