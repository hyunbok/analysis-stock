import 'package:intl/intl.dart';

/// 가격/수량/등락률 포맷 유틸.
class FormatUtils {
  FormatUtils._();

  static final _krwFormat = NumberFormat('#,###', 'ko_KR');
  static final _rateFormat = NumberFormat('0.00', 'en_US');
  static final _volumeFormat = NumberFormat('#,###', 'en_US');

  /// 한국 원화 포맷: 105,234,000
  static String formatKrw(double price) => _krwFormat.format(price);

  /// 등락률 포맷: +2.34% / -0.87% / 0.00%
  static String formatRate(double rate) =>
      '${rate >= 0 ? '+' : ''}${_rateFormat.format(rate)}%';

  /// 코인 수량 포맷: 소수점 최대 8자리, trailing zero 제거
  static String formatCoinAmount(double amount) =>
      amount.toStringAsFixed(8).replaceAll(RegExp(r'\.?0+$'), '');

  /// 거래량 포맷: 1,234,567
  static String formatVolume(double volume) => _volumeFormat.format(volume);

  /// 날짜 포맷: 2026-03-17
  static String formatDate(DateTime date) =>
      DateFormat('yyyy-MM-dd').format(date);

  /// 시간 포맷: 13:25:00
  static String formatTime(DateTime time) =>
      DateFormat('HH:mm:ss').format(time);

  /// 날짜+시간 포맷: 2026-03-17 13:25
  static String formatDateTime(DateTime dt) =>
      DateFormat('yyyy-MM-dd HH:mm').format(dt);

  /// API 키 마스킹: ****1234 (마지막 4자리만 표시)
  static String maskApiKey(String key) {
    if (key.length <= 4) return '****';
    return '****${key.substring(key.length - 4)}';
  }
}
