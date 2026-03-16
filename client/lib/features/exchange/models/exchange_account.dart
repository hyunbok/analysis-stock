import 'package:freezed_annotation/freezed_annotation.dart';

part 'exchange_account.freezed.dart';
part 'exchange_account.g.dart';

@freezed
class ExchangeAccount with _$ExchangeAccount {
  const factory ExchangeAccount({
    required String id,
    required String exchange,
    required String label,
    @Default(false) bool isConnected,
    @JsonKey(name: 'last_verified') DateTime? lastVerified,
  }) = _ExchangeAccount;

  factory ExchangeAccount.fromJson(Map<String, dynamic> json) =>
      _$ExchangeAccountFromJson(json);
}
