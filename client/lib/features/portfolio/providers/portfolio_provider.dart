import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../models/portfolio_summary.dart';
import '../repositories/portfolio_repository.dart';

part 'portfolio_provider.g.dart';

@riverpod
Future<PortfolioSummary> portfolio(PortfolioRef ref) {
  return ref.watch(portfolioRepositoryProvider).getPortfolio();
}
