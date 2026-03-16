import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../api/dio_client.dart';
import 'auth_state_provider.dart';
import 'storage_provider.dart';

part 'dio_provider.g.dart';

/// [Dio] 인스턴스를 제공한다.
///
/// [onUnauthorized] 콜백: refresh 실패 시 [authStateProvider]를 초기화하여
/// GoRouter redirect가 /login으로 전환되도록 트리거한다.
@Riverpod(keepAlive: true)
Dio dioClient(DioClientRef ref) {
  final storage = ref.watch(secureStorageProvider);
  return buildDio(
    storage,
    onUnauthorized: () {
      // ref.read: 콜백에서 호출되므로 구독 없이 읽기
      ref.read(authStateProvider.notifier).logout();
    },
  );
}
