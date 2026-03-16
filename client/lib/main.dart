import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hive_flutter/hive_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app/app.dart';
import 'core/providers/storage_provider.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 1. Hive 초기화 (캐시 저장소)
  await Hive.initFlutter();

  // 2. SharedPreferences 초기화 (앱 설정)
  final prefs = await SharedPreferences.getInstance();

  // 3. ProviderScope에 override 주입 후 앱 실행
  runApp(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
      ],
      child: const CoinTraderApp(),
    ),
  );
}
