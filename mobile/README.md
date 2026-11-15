# VeriScript for Android

Offline document capture and conversion. Paper & Ink is the light theme; Night Studio is the dark theme. Flutter provides the UI, bundled ML Kit reads Latin/Devanagari, and bundled OpenCV handles images. No Python service, account or first-launch model download. Release manifests remove Internet permission; debug builds permit Flutter's local debugger connection. The app asks once for notification permission (Android 13+) the first time a long job runs; declining only hides the progress notification.

## Implemented workflow

- Continuous camera photos, multiple gallery images and PDF imports, with drafts saved after each imported page.
- Automatic boundary detection, perspective correction and small-angle deskew; manual four-corner crop, rotation, reset and original comparison.
- Default enhancement: grayscale shadow flattening, light denoise and mild sharpening; small pages are enlarged up to 2× with Lanczos, bounded by 5000 pixels and 12.5 megapixels. Disable enhancement to keep color. Enlargement cannot reconstruct lost text.
- Offline English/Devanagari OCR, optional upright detection, editable lines and retained first readings.
- Visible page recognition and batch recognition of unread pages, with orientation/digit-check stages and cancellation that preserves the current page until recognition completes.
- Confirmation before replacing recognized text through image edits or re-recognition. One previous image/text version is saved with the draft and can be restored after reopening it.
- Files search across titles, folders and recognized text; folder filters and moves; confirmed permanent deletion of a document's private copies and exports.
- Digit checks: enlarged contrast-adjusted crops of number lines are read again by the **other** bundled engine when ML Kit is the reader (recognition only, about 70 ms per line on the emulator), and by the same engine when the Desktop reader is selected; groups are compared without changing the first reading. Measured on 123 number lines (2026-11-16): the other engine caught 2 of 4 wrong lines against 1 of 4 for the same engine, with fewer false alarms (6% vs 10%); the sample of wrong lines is small. Look-alike digits (Bengali digits, mixed scripts, letters inside numbers) are flagged separately. Alternatives and conflict/unclear/agreement states appear in review and correction JSON. Up to 80 digit-bearing lines are checked per page; remaining lines are marked unchecked. Numbers require human confirmation even when readings agree.
- Recorded/imported book video: stable-frame selection, deduplication, single-page or left/right spreads, review, exclusion and reorder. Experimental; completeness and crop accuracy need field testing.
- Combined image PDF, searchable image PDF, digital text-layout PDF, editable DOCX, TXT, Markdown and correction JSON. Android text layout shapes Devanagari for digital PDFs. Exports remain in app-private storage and can be shared through Android.
- Image and searchable PDFs are written page by page (`lib/pdf_stream.dart`): page JPEGs are copied in without re-encoding, so peak memory is one page. The searchable text layer is invisible (render mode 3), stretched to each line's box so selection lines up, and embeds only the Mukta glyphs used, with a ToUnicode map; copy and search return exact Unicode, Devanagari conjuncts included.
- Work that runs longer than two seconds (batch recognition, export, imports) shows a progress notification through a foreground service, so Android does not stop it when you switch apps. Drafts are still saved after every page.
- Settings → Diagnostics shows versions, settings, counts and recent error types (no titles, text, images or file paths) for a bug report. Nothing is sent; you choose whether to copy it.
- `document.json` stores files as paths relative to the document folder (schema 2), so a restored backup or moved storage keeps working. Older absolute paths are re-homed on load.

The digital text-layout PDF renders Devanagari correctly, but Android PDF text extraction can omit parts of conjuncts. Choose searchable scans or DOCX when preserving Nepali copy/search text matters.

## Limits and desktop differences

Android 10 (API 29) or newer. ARM64 is the phone build; x86_64 supports emulator verification. Target 4 GB RAM and 2 GB free space; 6 GB RAM and more storage for long books. These are unmeasured targets, not physical-device certification. Limit 150 pages per document and ten minutes per video, sampled at four frames/second. Photos over 30 megapixels are rejected. Imported originals are kept separately from normalized processing copies.

Development APKs use the Android debug signing key. Release builds are signed with your upload key when `android/key.properties` exists (see **Release signing** below); otherwise they fall back to the debug key and Gradle warns. Physical-phone acceptance is still outstanding.

This build does **not** claim desktop OCR accuracy or full parity. ML Kit remains the default. Settings → **Desktop reader (preview)** enables the experimental native RapidOCR backend for page and batch recognition; switching it off restores ML Kit. It uses the pinned desktop detector, English/Devanagari recognizers and English orientation classifier through ONNX Runtime. It is a native implementation, not execution of the Python desktop pipeline: DB polygon expansion differs at corners, and desktop layout analysis and the optional PyTorch letterpress reader are not included. The comparison harness selects it through `OfflineProcessor(language, engine: 'rapidocr')`. See [paired measurements](../evals/comparisons/2026-10-17/README.md) before choosing it; sharing models does not guarantee better accuracy or speed.

The optional Bodhan independent digit verifier, desktop calibration/date validators, learned cross-document correction memory, training-crop export and optional photo AI super-resolution are not ported. Agreement between the two bundled engines is evidence, not proof; same-engine agreement (Desktop reader mode) is weaker still. Desktop document enhancement is classical; the neural photo upscaler is CLI-only. Curved-page dewarping, reliable hand removal and guaranteed page completeness are not implemented.

## Build and verify

Use Flutter 3.44.9, Java 17 and the configured Android SDK/NDK. Set JAVA_HOME, ANDROID_HOME and ANDROID_SDK_ROOT; provide SDK paths in android/local.properties.

```powershell
flutter pub get
python tool/prepare_rapidocr.py
flutter analyze
flutter test
flutter build apk --release --target-platform android-arm64,android-x64 --split-per-abi
```

`prepare_rapidocr.py` copies the installed RapidOCR model cache or downloads the pinned artifacts, verifies SHA256, and bundles their license notices. Android builds verify this pack before packaging. The four model files add approximately 40 MB before APK compression; inference needs no network access. Model binaries are ignored by Git.

## Release signing

Create an upload keystore once and keep it out of the repository (`key.properties`, `*.jks` and `*.keystore` are git-ignored):

```powershell
keytool -genkey -v -keystore "$env:USERPROFILE\veriscript-upload.jks" -keyalg RSA -keysize 2048 -validity 10000 -alias upload
```

Then create `android/key.properties`:

```properties
storeFile=C:/Users/<you>/veriscript-upload.jks
storePassword=<store password>
keyAlias=upload
keyPassword=<key password>
```

Check that release builds use it with `cd android && ./gradlew :app:signingReport` (Variant `release` should show `Config: release`). Back up the keystore and passwords: Play requires the same upload key for every update. Before a Play release, raise `version:` in `pubspec.yaml`, since `versionCode` comes from the build number after `+`.

## Paired OCR comparison

From the repository root:

```powershell
python -m pip install -r evals/requirements-comparison.txt
python -m evals.harness.compare_apps prepare
python -m evals.harness.compare_apps desktop
python mobile/tool/compare_ocr.py --device emulator-5554
python -m evals.harness.compare_apps score
```

Before running the mobile comparison, disconnect Android Wi-Fi/data and enable airplane mode. The runner verifies there is no active default network. It installs a separate `.benchmark` application and clears only that disposable test sandbox on subsequent runs; the main app's document library is preserved. It tests the same image bytes with ML Kit and the experimental native backend. Competitor text exports belong in `build/ocr-comparison/pack/outputs/<app>/<page-id>.txt`, accompanied by `<page-id>.json` containing `image_sha256`, app version, export settings and test conditions. Missing pages or provenance prevent a complete ranking. Keep historical Hindi, synthetic Nepali and English results separate; this six-page smoke pack cannot establish market superiority or phone performance.

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
