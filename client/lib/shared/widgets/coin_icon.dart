import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import 'loading/shimmer_box.dart';

/// 코인 아이콘 위젯 — CachedNetworkImage + fallback.
class CoinIcon extends StatelessWidget {
  final String symbol;
  final String? imageUrl;
  final double size;

  const CoinIcon({
    super.key,
    required this.symbol,
    this.imageUrl,
    this.size = 36,
  });

  @override
  Widget build(BuildContext context) {
    if (imageUrl != null && imageUrl!.isNotEmpty) {
      return CachedNetworkImage(
        imageUrl: imageUrl!,
        width: size,
        height: size,
        imageBuilder: (context, imageProvider) => CircleAvatar(
          radius: size / 2,
          backgroundImage: imageProvider,
        ),
        placeholder: (context, url) => ShimmerBox(
          width: size,
          height: size,
          borderRadius: size / 2,
        ),
        errorWidget: (context, url, error) => _FallbackIcon(
          symbol: symbol,
          size: size,
        ),
      );
    }

    return _FallbackIcon(symbol: symbol, size: size);
  }
}

class _FallbackIcon extends StatelessWidget {
  final String symbol;
  final double size;

  const _FallbackIcon({required this.symbol, required this.size});

  @override
  Widget build(BuildContext context) {
    return CircleAvatar(
      radius: size / 2,
      backgroundColor: Theme.of(context).colorScheme.primaryContainer,
      child: Text(
        symbol.isNotEmpty ? symbol[0].toUpperCase() : '?',
        style: TextStyle(
          fontSize: size * 0.4,
          fontWeight: FontWeight.bold,
          color: Theme.of(context).colorScheme.onPrimaryContainer,
        ),
      ),
    );
  }
}
