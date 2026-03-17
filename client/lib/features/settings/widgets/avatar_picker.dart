import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

/// 프로필 아바타 선택 위젯.
///
/// 현재 아바타를 원형으로 표시하고, 오른쪽 하단 카메라 버튼으로
/// 사진 선택 액션을 제공한다.
class AvatarPicker extends StatelessWidget {
  final String? avatarUrl;
  final String displayName;
  final VoidCallback? onTap;
  final double size;

  const AvatarPicker({
    super.key,
    this.avatarUrl,
    required this.displayName,
    this.onTap,
    this.size = 96,
  });

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Stack(
      alignment: Alignment.bottomRight,
      children: [
        GestureDetector(
          onTap: onTap,
          child: CircleAvatar(
            radius: size / 2,
            backgroundColor: colorScheme.primaryContainer,
            child: avatarUrl != null
                ? ClipOval(
                    child: CachedNetworkImage(
                      imageUrl: avatarUrl!,
                      width: size,
                      height: size,
                      fit: BoxFit.cover,
                      errorWidget: (_, __, ___) => _Initials(
                        name: displayName,
                        size: size,
                        color: colorScheme.onPrimaryContainer,
                      ),
                    ),
                  )
                : _Initials(
                    name: displayName,
                    size: size,
                    color: colorScheme.onPrimaryContainer,
                  ),
          ),
        ),
        // 카메라 버튼
        GestureDetector(
          onTap: onTap,
          child: Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: colorScheme.primary,
              shape: BoxShape.circle,
              border: Border.all(
                color: colorScheme.surface,
                width: 2,
              ),
            ),
            child: Icon(
              Icons.camera_alt_outlined,
              size: 16,
              color: colorScheme.onPrimary,
            ),
          ),
        ),
      ],
    );
  }
}

class _Initials extends StatelessWidget {
  final String name;
  final double size;
  final Color color;

  const _Initials({
    required this.name,
    required this.size,
    required this.color,
  });

  String get _initials {
    final trimmed = name.trim();
    if (trimmed.isEmpty) return '?';
    return trimmed[0].toUpperCase();
  }

  @override
  Widget build(BuildContext context) {
    return Text(
      _initials,
      style: TextStyle(
        fontSize: size * 0.4,
        fontWeight: FontWeight.w600,
        color: color,
      ),
    );
  }
}
