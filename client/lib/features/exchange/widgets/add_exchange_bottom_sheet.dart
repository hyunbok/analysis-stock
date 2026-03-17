import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/exchange_provider.dart';
import '../repositories/exchange_repository.dart';

/// 거래소 API 키 등록 바텀시트.
class AddExchangeBottomSheet extends ConsumerStatefulWidget {
  const AddExchangeBottomSheet({super.key});

  static Future<void> show(BuildContext context) {
    return showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => const AddExchangeBottomSheet(),
    );
  }

  @override
  ConsumerState<AddExchangeBottomSheet> createState() =>
      _AddExchangeBottomSheetState();
}

class _AddExchangeBottomSheetState
    extends ConsumerState<AddExchangeBottomSheet> {
  final _formKey = GlobalKey<FormState>();
  final _accessKeyController = TextEditingController();
  final _secretKeyController = TextEditingController();
  String _selectedExchange = 'upbit';
  bool _isLoading = false;
  bool _obscureSecret = true;

  @override
  void dispose() {
    _accessKeyController.dispose();
    _secretKeyController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _isLoading = true);
    try {
      await ref.read(exchangeRepositoryProvider).createExchange(
            exchange: _selectedExchange,
            label: _selectedExchange == 'upbit' ? '업비트' : '코인원',
            apiKey: _accessKeyController.text.trim(),
            secretKey: _secretKeyController.text.trim(),
          );
      ref.invalidate(exchangeListProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('연결 실패: $e')),
      );
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
        24,
        24,
        24,
        MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Theme.of(context)
                      .colorScheme
                      .onSurfaceVariant
                      .withOpacity(0.4),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 20),
            Text('거래소 추가',
                style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 16),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'upbit', label: Text('업비트')),
                ButtonSegment(value: 'coinone', label: Text('코인원')),
              ],
              selected: {_selectedExchange},
              onSelectionChanged: (v) =>
                  setState(() => _selectedExchange = v.first),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _accessKeyController,
              decoration: const InputDecoration(
                labelText: 'Access Key',
                border: OutlineInputBorder(),
              ),
              validator: (v) =>
                  v == null || v.isEmpty ? 'Access Key를 입력해주세요' : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _secretKeyController,
              obscureText: _obscureSecret,
              decoration: InputDecoration(
                labelText: 'Secret Key',
                border: const OutlineInputBorder(),
                suffixIcon: IconButton(
                  icon: Icon(
                      _obscureSecret ? Icons.visibility_off : Icons.visibility),
                  onPressed: () =>
                      setState(() => _obscureSecret = !_obscureSecret),
                ),
              ),
              validator: (v) =>
                  v == null || v.isEmpty ? 'Secret Key를 입력해주세요' : null,
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _isLoading ? null : _save,
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(52),
              ),
              child: _isLoading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white),
                    )
                  : const Text('연결 테스트 후 저장'),
            ),
          ],
        ),
      ),
    );
  }
}
