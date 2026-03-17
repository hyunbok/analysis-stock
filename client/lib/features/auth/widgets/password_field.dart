import 'package:flutter/material.dart';

/// 비밀번호 입력 필드 — visibility 토글 포함.
class PasswordField extends StatefulWidget {
  final TextEditingController? controller;
  final String labelText;
  final String? errorText;
  final String? Function(String?)? validator;
  final TextInputAction textInputAction;
  final VoidCallback? onEditingComplete;

  const PasswordField({
    super.key,
    this.controller,
    this.labelText = '비밀번호',
    this.errorText,
    this.validator,
    this.textInputAction = TextInputAction.done,
    this.onEditingComplete,
  });

  @override
  State<PasswordField> createState() => _PasswordFieldState();
}

class _PasswordFieldState extends State<PasswordField> {
  bool _obscure = true;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: widget.controller,
      obscureText: _obscure,
      keyboardType: TextInputType.visiblePassword,
      textInputAction: widget.textInputAction,
      onEditingComplete: widget.onEditingComplete,
      validator: widget.validator,
      decoration: InputDecoration(
        labelText: widget.labelText,
        errorText: widget.errorText,
        suffixIcon: IconButton(
          icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility),
          onPressed: () => setState(() => _obscure = !_obscure),
        ),
        border: const OutlineInputBorder(),
      ),
    );
  }
}
