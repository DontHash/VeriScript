import 'package:flutter/material.dart';

/// Identifies the current dropdown option without relying on color alone.
class SelectionLabel extends StatelessWidget {
  const SelectionLabel(this.label, {super.key, required this.selected});

  final String label;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      selected: selected,
      child: Row(
        children: [
          Expanded(child: Text(label)),
          if (selected) ...[
            const SizedBox(width: 8),
            DecoratedBox(
              decoration: BoxDecoration(
                color: scheme.primary,
                shape: BoxShape.circle,
              ),
              child: Icon(Icons.check, size: 24, color: scheme.onPrimary),
            ),
          ],
        ],
      ),
    );
  }
}
