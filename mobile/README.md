# VeriScript for Android

Offline document capture and conversion. Paper & Ink is the light theme; Night Studio is the dark theme. Flutter provides the UI, bundled ML Kit reads Latin/Devanagari, and bundled OpenCV handles images. No Python service, account or first-launch model download. Release manifests remove Internet permission; debug builds permit Flutter's local debugger connection.

## Implemented workflow

- Continuous camera photos, multiple gallery images and PDF imports, with drafts saved after each imported page.
- Automatic boundary detection, perspective correction and small-angle deskew; manual four-corner crop, rotation, reset and original comparison.
- Default enhancement: grayscale shadow flattening, light denoise and mild sharpening; small pages are enlarged up to 2× with Lanczos, bounded by 5000 pixels and 12.5 megapixels. Disable enhancement to keep color. Enlargement cannot reconstruct lost text.
- Offline English/Devanagari OCR, optional upright detection, editable lines and retained first readings.
- Visible page recognition and batch recognition of unread pages, with orientation/digit-check stages and cancellation that preserves the current page until recognition completes.
- Confirmation before replacing recognized text through image edits or re-recognition. One previous image/text version is saved with the draft and can be restored after reopening it.
- Files search across titles, folders and recognized text; folder filters and moves; confirmed permanent deletion of a document's private copies and exports.
- Digit checks: enlarged contrast-adjusted crops are read again by the **same** engine; groups are compared without changing the first reading. Alternatives and conflict/unclear/agreement states appear in review and correction JSON. Up to 80 digit-bearing lines are checked per page; remaining lines are marked unchecked. Numbers require human confirmation even when readings agree.
- Recorded/imported book video: stable-frame selection, deduplication, single-page or left/right spreads, review, exclusion and reorder. Experimental; completeness and crop accuracy need field testing.
- Combined image PDF, searchable image PDF, digital text-layout PDF, editable DOCX, TXT, Markdown and correction JSON. Android text layout shapes Devanagari for digital PDFs. Exports remain in app-private storage and can be shared through Android.

The digital text-layout PDF renders Devanagari correctly, but Android PDF text extraction can omit parts of conjuncts. Choose searchable scans or DOCX when preserving Nepali copy/search text matters.

## Limits and desktop differences

Android 10 (API 29) or newer. ARM64 is the phone build; x86_64 supports emulator verification. Target 4 GB RAM and 2 GB free space; 6 GB RAM and more storage for long books. These are unmeasured targets, not physical-device certification. Limit 150 pages per document and ten minutes per video, sampled at four frames/second. Photos over 30 megapixels are rejected. Imported originals are kept separately from normalized processing copies.

Development APKs use the Android debug signing key. Production signing and physical-phone acceptance remain outstanding.

This build does **not** claim desktop OCR accuracy or full parity. ML Kit replaces the Python OCR engines. The optional Bodhan independent digit verifier, desktop calibration/date validators, learned cross-document correction memory, training-crop export and optional photo AI super-resolution are not ported. Same-engine digit agreement is not independent verification. Desktop document enhancement is classical; the neural photo upscaler is CLI-only. Curved-page dewarping, reliable hand removal and guaranteed page completeness are not implemented.

## Build and verify

Use Flutter 3.44.9, Java 17 and the configured Android SDK/NDK. Set JAVA_HOME, ANDROID_HOME and ANDROID_SDK_ROOT; provide SDK paths in android/local.properties.

```powershell
flutter pub get
flutter analyze
flutter test
flutter build apk --release --target-platform android-arm64,android-x64 --split-per-abi
```

Run Flutter commands **sequentially** here. Analysis/tests can regenerate the plugin registrant during release compilation, incorrectly introducing the debug integration-test plugin into release registration.

For Android integration, disable Wi-Fi/data, enable airplane mode and verify dumpsys connectivity reports no active default network before the first app launch. Debug tests use ADB loopback; OCR remains offline.

```powershell
python tool/verify_android.py --device emulator-5554
```

Integration coverage: real enhancement, English/Devanagari OCR, digit evidence, orientation, crop validation, all exports, PDF rendering, draft persistence and book-video ordering/deduplication. Synthetic fixtures do not prove field accuracy. See docs/VERIFICATION.md for actual results and docs/ARTEMIS.md for Project Auto tool reuse.

See [P1 implementation and checks](docs/P1.md) for the workflow changes following the customer audit and the remaining physical-device acceptance work.

See [P2 appearance and review checks](docs/P2.md) for dark-mode hierarchy, larger grid/list previews and export guidance.

See [P3 typography and selection checks](docs/P3.md) for the bundled display font and consistent selected controls.

The runner generates a synthetic book fixture if needed, checks disconnected Android networking, and transfers the fixture over ADB after Flutter reinstalls the test app. The fixture is not included in production APKs.
