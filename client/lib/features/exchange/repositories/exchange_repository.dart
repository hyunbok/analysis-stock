import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/providers/dio_provider.dart';
import '../models/exchange_account.dart';

part 'exchange_repository.g.dart';

@riverpod
ExchangeRepository exchangeRepository(ExchangeRepositoryRef ref) {
  return ExchangeRepository(ref.watch(dioClientProvider));
}

class ExchangeRepository {
  final Dio _dio;

  const ExchangeRepository(this._dio);

  Future<List<ExchangeAccount>> getExchanges() async {
    final res =
        await _dio.get<Map<String, dynamic>>('/api/v1/exchanges');
    final items = res.data!['data'] as List<dynamic>;
    return items
        .map((e) => ExchangeAccount.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<ExchangeAccount> createExchange({
    required String exchange,
    required String label,
    required String apiKey,
    required String secretKey,
  }) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/api/v1/exchanges',
      data: {
        'exchange': exchange,
        'label': label,
        'api_key': apiKey,
        'secret_key': secretKey,
      },
    );
    return ExchangeAccount.fromJson(
        res.data!['data'] as Map<String, dynamic>);
  }

  Future<void> deleteExchange(String id) async {
    await _dio.delete<void>('/api/v1/exchanges/$id');
  }

  Future<ExchangeAccount> verifyExchange(String id) async {
    final res = await _dio.post<Map<String, dynamic>>(
        '/api/v1/exchanges/$id/verify');
    return ExchangeAccount.fromJson(
        res.data!['data'] as Map<String, dynamic>);
  }
}
