import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/dio_provider.dart';
import '../models/portfolio_summary.dart';

part 'portfolio_repository.g.dart';

@riverpod
PortfolioRepository portfolioRepository(PortfolioRepositoryRef ref) {
  return PortfolioRepository(ref.watch(dioClientProvider));
}

class PortfolioRepository {
  final Dio _dio;

  const PortfolioRepository(this._dio);

  Future<PortfolioSummary> getPortfolio() async {
    final res =
        await _dio.get<Map<String, dynamic>>('/api/v1/portfolio');
    return PortfolioSummary.fromJson(
        res.data!['data'] as Map<String, dynamic>);
  }

  Future<ExchangePortfolio> getExchangePortfolio(
      String exchangeId) async {
    final res = await _dio
        .get<Map<String, dynamic>>('/api/v1/portfolio/$exchangeId');
    return ExchangePortfolio.fromJson(
        res.data!['data'] as Map<String, dynamic>);
  }
}
