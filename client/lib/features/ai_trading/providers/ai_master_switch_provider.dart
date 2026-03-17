import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'ai_master_switch_provider.g.dart';

/// AI 전체 ON/OFF 마스터 스위치 상태.
///
/// AiTradingNotifier.toggle()은 개별 코인 설정 — 마스터 스위치는 전체 일괄 ON/OFF.
@riverpod
class AiMasterSwitch extends _$AiMasterSwitch {
  @override
  bool build() => false;

  void toggle() => state = !state;
  void set(bool value) => state = value;
}
