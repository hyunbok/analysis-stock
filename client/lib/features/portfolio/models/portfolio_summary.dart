import 'package:freezed_annotation/freezed_annotation.dart';

part 'portfolio_summary.freezed.dart';
part 'portfolio_summary.g.dart';

@freezed
class CoinHolding with _$CoinHolding {
  const factory CoinHolding({
    required String symbol,
    required double amount,
    @JsonKey(name: 'avg_buy_price') required double avgBuyPrice,
    @JsonKey(name: 'current_price') required double currentPrice,
    @JsonKey(name: 'pnl_rate') required double pnlRate,
  }) = _CoinHolding;

  factory CoinHolding.fromJson(Map<String, dynamic> json) =>
      _$CoinHoldingFromJson(json);
}

@freezed
class ExchangePortfolio with _$ExchangePortfolio {
  const factory ExchangePortfolio({
    required String exchange,
    @JsonKey(name: 'total_asset') required double totalAsset,
    required List<CoinHolding> holdings,
  }) = _ExchangePortfolio;

  factory ExchangePortfolio.fromJson(Map<String, dynamic> json) =>
      _$ExchangePortfolioFromJson(json);
}

@freezed
class PortfolioSummary with _$PortfolioSummary {
  const factory PortfolioSummary({
    @JsonKey(name: 'total_asset') required double totalAsset,
    @JsonKey(name: 'total_pnl') required double totalPnl,
    required List<ExchangePortfolio> exchanges,
  }) = _PortfolioSummary;

  factory PortfolioSummary.fromJson(Map<String, dynamic> json) =>
      _$PortfolioSummaryFromJson(json);
}
