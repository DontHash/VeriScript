import 'package:flutter/material.dart';

/// First-run introduction: what stays on the phone, why the camera is
/// needed, and why numbers must be checked. Shown once, before Android's
/// own camera permission prompt, so that prompt is never a surprise.
class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key, required this.onDone});

  final VoidCallback onDone;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    Widget point(IconData icon, String title, String body) => Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: MergeSemantics(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 28, color: scheme.onSurfaceVariant),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: const TextStyle(
                      fontSize: 19,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(body, style: TextStyle(color: scheme.onSurfaceVariant)),
                ],
              ),
            ),
          ],
        ),
      ),
    );

    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 40, 24, 24),
          children: [
            Semantics(
              header: true,
              child: Text(
                'Welcome to VeriScript',
                style: Theme.of(context).textTheme.displayMedium,
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              'Turn paper into searchable documents in Nepali, Hindi and English.',
              style: TextStyle(fontSize: 17),
            ),
            const SizedBox(height: 32),
            point(
              Icons.phonelink_lock_outlined,
              'Everything stays on your phone',
              'Pages are read on this device. No account, no upload, no internet needed.',
            ),
            point(
              Icons.photo_camera_outlined,
              'The camera is only for your pages',
              'Android will ask for camera access when you first scan. You can import photos and PDFs instead.',
            ),
            point(
              Icons.fact_check_outlined,
              'Numbers are checked, not guessed',
              'Digits that may be misread are flagged for you to confirm before you export.',
            ),
          ],
        ),
      ),
      // Pinned so it is always on screen, whatever the text size.
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.fromLTRB(24, 8, 24, 16),
        child: FilledButton(
          onPressed: onDone,
          child: const Text('Get started'),
        ),
      ),
    );
  }
}
